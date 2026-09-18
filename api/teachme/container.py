from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cached_property

import psycopg
from psycopg_pool import ConnectionPool

from teachme.adapters.db.engine import connect
from teachme.adapters.db.migrate import ensure_schema_current
from teachme.adapters.db.pool import make_pool
from teachme.adapters.embeddings.fake import FakeEmbedder
from teachme.adapters.file_store.local import LocalFileStore
from teachme.adapters.file_store.prefixed import PrefixedFileStore
from teachme.adapters.llm.fake import FakeLLM
from teachme.adapters.reranker.noop import NoopReranker
from teachme.generation.fake_responders import default_responders as generation_responders
from teachme.generation.fake_responders import default_text_responder
from teachme.grading.fake_responders import default_responders as grading_responders
from teachme.ingestion.fake_responders import default_responders as ingestion_responders
from teachme.ports.embeddings import Embedder
from teachme.ports.file_store import FileStore
from teachme.ports.llm import LLMProvider
from teachme.ports.reranker import Reranker
from teachme.repositories.usage import UsageRepository
from teachme.scope import Scope
from teachme.services.corpus_cache import CorpusCache
from teachme.settings import Settings
from teachme.telemetry.prices import PriceTable
from teachme.telemetry.recording import RecordingEmbedder, RecordingLLM
from teachme.telemetry.usage import UsageRecorder


class ConfigurationError(Exception):
    pass


def _secret(value) -> str | None:
    return value.get_secret_value() if value is not None else None


# The console ids a federation exchange is made against. The first two are what the exchange
# itself needs; the other two narrow the token it mints, and the server picks a default without
# them - so only the first two are required once federation is asked for at all.
FEDERATION_IDS = (
    "anthropic_federation_rule_id",
    "anthropic_organization_id",
    "anthropic_service_account_id",
    "anthropic_workspace_id",
)
REQUIRED_FEDERATION_IDS = FEDERATION_IDS[:2]


def build_identity(settings: Settings) -> Callable[[], str] | None:
    """What hands the Anthropic SDK this deployment's OIDC token, or None when it authenticates
    with an API key instead.

    The two halves - the console ids and a provider that can produce a token - are useless apart,
    and either one alone is a deployment that would fail on its first model call rather than at
    startup: ids without a provider have nothing to exchange, a provider without ids has nothing
    to exchange against. Both are refused here, by name."""
    configured = [name for name in FEDERATION_IDS if getattr(settings, name)]
    if settings.identity_provider == "none":
        if configured:
            raise ConfigurationError(
                f"{', '.join(name.upper() for name in configured)} set with IDENTITY_PROVIDER=none:"
                " nothing would mint the OIDC token they are exchanged for. Set"
                " IDENTITY_PROVIDER=vercel_oidc (on Vercel) or file (with IDENTITY_TOKEN_FILE),"
                " or unset the federation ids and use ANTHROPIC_API_KEY."
            )
        return None
    missing = [name.upper() for name in REQUIRED_FEDERATION_IDS if not getattr(settings, name)]
    if missing:
        raise ConfigurationError(
            f"IDENTITY_PROVIDER={settings.identity_provider} requires {', '.join(missing)}:"
            " an OIDC token is exchanged against a federation rule, not presented on its own."
        )
    if settings.identity_provider == "file":
        if not settings.identity_token_file:
            raise ConfigurationError("IDENTITY_PROVIDER=file requires IDENTITY_TOKEN_FILE")
        from teachme.adapters.identity.aws import FileIdentity

        return FileIdentity(settings.identity_token_file)
    from teachme.adapters.identity.vercel_oidc import VercelOidcIdentity

    return VercelOidcIdentity()


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        from teachme.adapters.llm.anthropic import AnthropicLLM, workload_identity

        identity = build_identity(settings)
        if identity is None:
            return AnthropicLLM(api_key=_secret(settings.anthropic_api_key))
        return AnthropicLLM(
            credentials=workload_identity(
                identity=identity,
                federation_rule_id=settings.anthropic_federation_rule_id,
                organization_id=settings.anthropic_organization_id,
                service_account_id=settings.anthropic_service_account_id,
                workspace_id=settings.anthropic_workspace_id,
            )
        )
    return FakeLLM(
        {**ingestion_responders(), **generation_responders(), **grading_responders()},
        text_responder=default_text_responder(),
    )


def build_embedder(settings: Settings) -> Embedder:
    if settings.embeddings_provider == "voyage":
        from teachme.adapters.embeddings.voyage import VoyageEmbedder

        return VoyageEmbedder(model=settings.embedding_model, api_key=_secret(settings.voyage_api_key))
    return FakeEmbedder()


def build_reranker(settings: Settings) -> Reranker:
    if settings.reranker_provider == "voyage":
        from teachme.adapters.reranker.voyage import VoyageReranker

        return VoyageReranker(model=settings.rerank_model, api_key=_secret(settings.voyage_api_key))
    return NoopReranker()


def build_file_store(settings: Settings) -> FileStore:
    if settings.file_store == "local":
        return LocalFileStore(settings.local_files_dir)
    if settings.file_store == "vercel_blob":
        from teachme.adapters.file_store.vercel_blob import VercelBlobFileStore

        return VercelBlobFileStore(prefix=settings.blob_prefix, token=_secret(settings.blob_read_write_token))
    if not settings.s3_bucket:
        raise ConfigurationError("FILE_STORE=s3 requires S3_BUCKET")
    from teachme.adapters.file_store.s3 import S3FileStore

    return S3FileStore(bucket=settings.s3_bucket, region=settings.aws_region)


class Container:
    """Process-wide singletons - settings, adapters, caches, the connection pool - plus a default
    Scope on one connection for the CLI. Attribute lookups for repositories and services fall
    through to that default scope, so `container.pipeline` keeps working; an HTTP request takes
    its own scope from the pool with `request_scope()`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    # infrastructure -------------------------------------------------------------------------
    @cached_property
    def conn(self) -> psycopg.Connection:
        return connect(self.settings.database_url)

    @cached_property
    def pool(self) -> ConnectionPool:
        """Request connections. Opened lazily: the CLI never touches it."""
        return make_pool(self.settings.database_url)

    @cached_property
    def usage_conn(self) -> psycopg.Connection:
        """Telemetry writes here, on its own autocommit connection: a usage row records money
        already spent, so it must not be rolled back with the pipeline step that failed."""
        return connect(self.settings.database_url, autocommit=True)

    @cached_property
    def http_client(self):
        """Outgoing HTTP this process makes on its own behalf - today only the vercel_function
        job runner calling this deployment back. One client, so connections are reused; built by
        that adapter, so httpx is imported only by a deployment that has selected it."""
        from teachme.adapters.job_runner.vercel_function import make_http_client

        return make_http_client()

    @property
    def has_pool(self) -> bool:
        """Whether this container is serving requests. `pool` is a cached_property, so asking
        for it would open one; this only reports whether one is already open, which is what
        tells code written for both the CLI and the request path which of the two it is in."""
        return "pool" in self.__dict__

    @cached_property
    def prices(self) -> PriceTable:
        return PriceTable()

    @cached_property
    def usage_repo(self) -> UsageRepository:
        return UsageRepository(self.usage_conn)

    @cached_property
    def usage_recorder(self) -> UsageRecorder:
        return UsageRecorder(self.usage_repo, self.prices)

    @cached_property
    def llm(self) -> LLMProvider:
        return RecordingLLM(build_llm(self.settings), self.usage_recorder)

    @cached_property
    def embedder(self) -> Embedder:
        return RecordingEmbedder(build_embedder(self.settings), self.usage_recorder)

    @cached_property
    def reranker(self) -> Reranker:
        return build_reranker(self.settings)

    @cached_property
    def files(self) -> FileStore:
        return build_file_store(self.settings)

    @cached_property
    def bundle_stores(self) -> list[FileStore]:
        stores: list[FileStore] = [PrefixedFileStore(self.files, "digest/")]
        if self.settings.write_local_bundle:
            stores.append(LocalFileStore(self.settings.digest_dir))
        return stores

    @cached_property
    def corpus_cache(self) -> CorpusCache:
        return CorpusCache(max_entries=self.settings.corpus_cache_max_entries)

    # scopes ---------------------------------------------------------------------------------
    @cached_property
    def scope(self) -> Scope:
        """The CLI's scope, on the container's single connection."""
        return Scope(self, self.conn)

    def __getattr__(self, name: str):
        # Only reached for names this class does not define: the repositories and services that
        # now live on a Scope. The guard keeps a half-built container from recursing forever.
        if name.startswith("_") or name in ("settings", "scope", "conn", "usage_conn", "pool"):
            raise AttributeError(name)
        if self.has_pool:
            raise AttributeError(
                f"{name!r} is not reachable on a container serving requests: a request takes its"
                " own scope from the pool (`request_scope`), and falling through here would put"
                " every request on the single CLI connection, in one shared transaction"
            )
        return getattr(self.scope, name)

    @contextmanager
    def request_scope(self) -> Iterator[Scope]:
        """One request, one pooled connection. `pool.connection()` commits a clean exit, rolls
        back a failed one and returns the connection either way, so no request can leak it."""
        with self.pool.connection() as conn:
            with Scope(self, conn).active() as scope:
                yield scope

    # lifecycle ------------------------------------------------------------------------------
    def check_ready(self) -> None:
        """Fail fast with a named reason instead of on the first request."""
        ensure_schema_current(self.conn)
        expected = self.scope.search.dimension()
        if self.embedder.dimension != expected:
            raise ConfigurationError(
                f"embedder {self.embedder.model!r} has dimension {self.embedder.dimension}, "
                f"chunks table expects {expected}"
            )
        # Touch every adapter so a missing/invalid configuration surfaces here, at startup,
        # rather than on the first request that happens to need it. Identity is checked even on
        # the fake stack: half a federation is a deployment that cannot authenticate, whichever
        # provider it would have used it for.
        build_identity(self.settings)
        _ = (self.files, self.scope.job_runner, self.llm, self.reranker)
        self.conn.rollback()

    def close(self) -> None:
        for name in ("conn", "usage_conn", "http_client"):
            if name in self.__dict__:
                self.__dict__[name].close()
        if self.has_pool:
            self.__dict__["pool"].close()
