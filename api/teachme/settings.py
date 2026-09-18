from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from teachme.domain.languages import LANGUAGES
from teachme.domain.relevance.scorer import RelevanceThresholds


class Settings(BaseSettings):
    """Every configurable value in one place. Nothing else reads os.environ."""

    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    # 5433: a native Postgres occupies 5432 on the dev machine; docker-compose maps to 5433
    database_url: str = "postgresql://teachme:teachme@localhost:5433/teachme"

    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    embeddings_provider: Literal["voyage", "fake"] = "voyage"
    reranker_provider: Literal["voyage", "noop"] = "voyage"
    file_store: Literal["local", "vercel_blob", "s3"] = "local"
    job_runner: Literal["inprocess", "sqs", "vercel_function"] = "inprocess"

    local_files_dir: Path = Path("data/files")
    digest_dir: Path = Path("digest")
    write_local_bundle: bool = True
    blob_prefix: str = "teach-me"
    aws_region: str = "eu-central-1"
    s3_bucket: str | None = None
    sqs_queue_url: str | None = None
    # JOB_RUNNER=vercel_function: the function calls itself back at {self_base_url}/api/jobs/run,
    # authenticating with this shared secret. Unset self_base_url means https://{VERCEL_URL},
    # which Vercel sets per deployment, so a preview calls its own preview and not production.
    job_runner_secret: SecretStr | None = None
    self_base_url: str | None = None
    # Set by Vercel on every deployment: that deployment's own host, without a scheme. Read here
    # rather than from os.environ, because settings is the only place that touches the environment.
    vercel_url: str | None = None

    model_read_pages: str = "claude-opus-5"
    model_detect_language: str = "claude-opus-5"
    model_contextualize: str = "claude-opus-5"
    model_generation: str = "claude-opus-5"
    model_grader: str = "claude-sonnet-5"
    model_relevance_check: str = "claude-haiku-4-5"
    model_reexplain: str = "claude-opus-5"
    embedding_model: str = "voyage-4"
    rerank_model: str = "rerank-2.5"

    enabled_languages: list[str] = ["he", "en", "pt"]
    allowed_upload_types: list[str] | None = None
    max_pages_per_source: int = 400
    # The largest upload the admin route accepts. A declared Content-Length over it is refused by
    # a middleware before the body is read; a chunked body is measured once the form is parsed.
    # Vercel itself refuses a request body over 100 MB, so this can only narrow that.
    max_upload_bytes: int = 50 * 1024 * 1024
    pages_per_read_batch: int = 6
    pages_per_chunk_batch: int = 6
    # How long a job may sit `running` before the sweep calls its invocation dead and marks it
    # failed, so a later delivery can claim and retry it. A function that hits its duration limit
    # writes nothing on its way out, so nothing else would ever move that row. Keep this at the
    # function's own limit (vercel.json maxDuration): a job still inside it is not stale.
    job_stale_after_seconds: int = 300
    max_answer_chars: int = 1500
    max_answers_per_minute: int = 20
    max_rejections_per_question: int = 2
    reinforce_sections_cap: int = 3
    # Rendered subject corpora kept in the per-process cache; a corpus is a whole subject's
    # text, so the cache is capped and evicts the least recently used entry.
    corpus_cache_max_entries: int = 8
    # Width in pixels a source page is rasterized to for GET .../pages/{index}/image. Part of the
    # cache key (thumbnails/{source_id}/NNN-w{width}.png), so changing it does not invalidate
    # images already rendered at the old width - they simply sit alongside the new ones.
    thumbnail_width: int = Field(default=800, ge=64, le=2400)

    # Relevance bands: at or above `high` an answer skips the relevance check, below `low` it is
    # LOW. Both go to the check, so these only move where the cheap model call is spent.
    relevance_high: float = 0.5
    relevance_low: float = 0.15
    relevance_thresholds: dict[str, RelevanceThresholds] = {}
    """Per-language overrides for the two thresholds above, because the lexical score is not
    equally generous in every language: RELEVANCE_THRESHOLDS={"he": {"high": 0.4, "low": 0.1}}."""

    # Authentication: Clerk's JWKS endpoint for this instance. Unset means no guard is built and
    # every authenticated route refuses, which is what a local run without Clerk should do.
    clerk_jwks_url: str | None = None

    # Credentials, passed explicitly to adapters instead of adapters reading os.environ themselves.
    anthropic_api_key: SecretStr | None = None
    # Workload identity federation (spec section 9): instead of a long-lived key, the deployment
    # presents an OIDC token it is handed per invocation and the SDK exchanges it for a short-lived
    # access token against this rule. All four come from the Anthropic console; the rule and the
    # organization are what the exchange needs, the service account and workspace narrow what the
    # minted token may do. Set together with IDENTITY_PROVIDER, or not at all.
    anthropic_federation_rule_id: str | None = None
    anthropic_organization_id: str | None = None
    anthropic_service_account_id: str | None = None
    anthropic_workspace_id: str | None = None
    # Where that OIDC token comes from. `vercel_oidc` reads the x-vercel-oidc-token header of the
    # request being served, so it only works inside a request; `file` re-reads a file on every
    # exchange (a projected service-account token, and what a CLI or worker run uses); `none`
    # means this deployment authenticates with ANTHROPIC_API_KEY.
    identity_provider: Literal["none", "vercel_oidc", "file"] = "none"
    identity_token_file: Path | None = None
    voyage_api_key: SecretStr | None = None
    blob_read_write_token: SecretStr | None = None

    @property
    def job_callback_base_url(self) -> str | None:
        """Where the vercel_function runner posts a job back to this same deployment."""
        if self.self_base_url:
            return self.self_base_url.rstrip("/")
        return f"https://{self.vercel_url}" if self.vercel_url else None

    def relevance_thresholds_for(self, language_code: str) -> RelevanceThresholds:
        """The override for this language, or the defaults."""
        return self.relevance_thresholds.get(language_code) or RelevanceThresholds(
            high=self.relevance_high, low=self.relevance_low
        )

    @model_validator(mode="after")
    def _ordered_relevance_thresholds(self) -> Settings:
        """A low above the high would leave the UNCERTAIN band empty and silently reclassify
        every answer, so the ordering is checked rather than trusted."""
        configured = [("default", self.relevance_thresholds_for("")), *self.relevance_thresholds.items()]
        for name, thresholds in configured:
            if not 0.0 <= thresholds.low <= thresholds.high <= 1.0:
                raise ValueError(
                    f"relevance thresholds for {name!r} must satisfy 0 <= low <= high <= 1, "
                    f"got low={thresholds.low}, high={thresholds.high}"
                )
        return self

    @field_validator("enabled_languages")
    @classmethod
    def _known_languages(cls, value: list[str]) -> list[str]:
        unknown = [code for code in value if code not in LANGUAGES]
        if unknown:
            raise ValueError(f"unsupported languages: {unknown}; supported: {sorted(LANGUAGES)}")
        return value
