from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teachme.adapters.identity import IdentityUnavailable
from teachme.adapters.identity.aws import FileIdentity
from teachme.adapters.identity.vercel_oidc import (
    OIDC_HEADER,
    CarryVercelOidcToken,
    VercelOidcIdentity,
    current_token,
)
from teachme.container import ConfigurationError, build_identity, build_llm
from teachme.settings import Settings

FEDERATION = dict(
    llm_provider="anthropic",
    identity_provider="vercel_oidc",
    anthropic_federation_rule_id="fedrule_1",
    anthropic_organization_id="11111111-2222-3333-4444-555555555555",
    anthropic_service_account_id="svcacct_1",
    anthropic_workspace_id="wrkspc_1",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Settings reads os.environ; a developer's shell must not decide what these tests see."""
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


@pytest.fixture
def stub_anthropic(monkeypatch):
    """Records the kwargs `AnthropicLLM` builds its client with, so a test can see which
    credential the container chose without constructing a real SDK client."""
    import teachme.adapters.llm.anthropic as adapter

    calls: list[dict] = []

    def record(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(adapter, "Anthropic", record)
    return calls


# the context var and its middleware -----------------------------------------------------------


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CarryVercelOidcToken)

    @app.get("/token")
    def read() -> dict[str, str | None]:
        return {"seen": current_token(), "identity": _identity_or_none()}

    def _identity_or_none() -> str | None:
        try:
            return VercelOidcIdentity()()
        except IdentityUnavailable:
            return None

    return app


def test_the_middleware_carries_the_header_into_the_context_var():
    with TestClient(_app()) as client:
        body = client.get("/token", headers={OIDC_HEADER: "jwt-abc"}).json()
    assert body == {"seen": "jwt-abc", "identity": "jwt-abc"}


def test_a_request_without_the_header_leaves_no_token():
    with TestClient(_app()) as client:
        assert client.get("/token").json() == {"seen": None, "identity": None}


def test_the_token_does_not_outlive_the_request():
    """Set and reset around each request: a token left behind would be handed to the next
    request's token exchange, which is another deployment's credential."""
    with TestClient(_app()) as client:
        client.get("/token", headers={OIDC_HEADER: "jwt-abc"})
    assert current_token() is None


def test_the_app_installs_the_middleware(make_container):
    from teachme.app import create_app

    app = create_app(make_container())
    assert CarryVercelOidcToken in [middleware.cls for middleware in app.user_middleware]


def test_the_identity_refuses_outside_a_request():
    with pytest.raises(IdentityUnavailable, match="x-vercel-oidc-token"):
        VercelOidcIdentity()()


# the file identity ----------------------------------------------------------------------------


def test_the_file_identity_rereads_the_file_on_every_call(tmp_path):
    """Projected token files are rotated in place, so a cached read would keep presenting an
    expired assertion until the process restarts."""
    path = tmp_path / "token"
    path.write_text("first\n")
    identity = FileIdentity(path)
    assert identity() == "first"
    path.write_text("  second  \n")
    assert identity() == "second"


def test_a_missing_or_empty_token_file_is_an_identity_error(tmp_path):
    missing = FileIdentity(tmp_path / "nope")
    with pytest.raises(IdentityUnavailable, match="nope"):
        missing()
    empty = tmp_path / "token"
    empty.write_text("\n")
    with pytest.raises(IdentityUnavailable, match="empty"):
        FileIdentity(empty)()


# what the container builds --------------------------------------------------------------------


def test_without_federation_the_client_is_built_with_the_api_key(stub_anthropic):
    settings = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="sk-x")
    assert build_identity(settings) is None
    build_llm(settings)
    assert stub_anthropic[0]["api_key"] == "sk-x" and "credentials" not in stub_anthropic[0]


def test_with_federation_the_client_is_built_with_workload_identity_credentials(stub_anthropic):
    from anthropic import WorkloadIdentityCredentials

    settings = Settings(_env_file=None, anthropic_api_key="sk-x", **FEDERATION)
    build_llm(settings)
    kwargs = stub_anthropic[0]
    # The key is not passed alongside: the SDK warns that a static credential shadows a provider,
    # and a deployment that has moved to federation should have no key left to shadow it with.
    assert "api_key" not in kwargs
    credentials = kwargs["credentials"]
    assert isinstance(credentials, WorkloadIdentityCredentials)
    assert credentials._federation_rule_id == "fedrule_1"
    assert credentials._organization_id == FEDERATION["anthropic_organization_id"]
    assert credentials._service_account_id == "svcacct_1"
    assert credentials._workspace_id == "wrkspc_1"
    assert isinstance(credentials._identity_token_provider, VercelOidcIdentity)
    credentials.close()


def test_the_file_provider_builds_a_file_identity(tmp_path, stub_anthropic):
    path = tmp_path / "token"
    path.write_text("jwt-from-disk")
    settings = Settings(
        _env_file=None, **{**FEDERATION, "identity_provider": "file", "identity_token_file": path}
    )
    identity = build_identity(settings)
    assert isinstance(identity, FileIdentity) and identity() == "jwt-from-disk"


def test_federation_ids_without_a_provider_are_refused():
    settings = Settings(_env_file=None, **{**FEDERATION, "identity_provider": "none"})
    with pytest.raises(ConfigurationError, match="IDENTITY_PROVIDER"):
        build_identity(settings)


def test_a_provider_without_federation_ids_is_refused():
    settings = Settings(_env_file=None, llm_provider="anthropic", identity_provider="vercel_oidc")
    with pytest.raises(ConfigurationError, match="ANTHROPIC_FEDERATION_RULE_ID"):
        build_identity(settings)


def test_federation_without_the_organization_id_is_refused():
    settings = Settings(_env_file=None, **{**FEDERATION, "anthropic_organization_id": None})
    with pytest.raises(ConfigurationError, match="ANTHROPIC_ORGANIZATION_ID"):
        build_identity(settings)


def test_the_file_provider_without_a_file_is_refused():
    settings = Settings(_env_file=None, **{**FEDERATION, "identity_provider": "file"})
    with pytest.raises(ConfigurationError, match="IDENTITY_TOKEN_FILE"):
        build_identity(settings)


def test_check_ready_refuses_a_half_configured_federation(make_container):
    container = make_container(identity_provider="vercel_oidc")
    with pytest.raises(ConfigurationError, match="ANTHROPIC_FEDERATION_RULE_ID"):
        container.check_ready()
