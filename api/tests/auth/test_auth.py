from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from teachme.app import create_app
from teachme.auth.clerk import UserContext, make_clerk_guard, user_from_claims
from teachme.auth.roles import require_admin
from teachme.routes.schemas import ErrorResponse


def test_user_from_claims_reads_sub_and_role_from_metadata_or_top_level():
    creds = SimpleNamespace(decoded={"sub": "user_1", "public_metadata": {"role": "admin"}})
    assert user_from_claims(creds) == UserContext(user_id="user_1", role="admin")
    creds = SimpleNamespace(decoded={"sub": "user_2", "role": "student"})
    assert user_from_claims(creds).role == "student"
    creds = SimpleNamespace(decoded={"sub": "user_3"})
    assert user_from_claims(creds).role == "student"


def test_a_token_without_a_subject_is_rejected():
    creds = SimpleNamespace(decoded={"role": "admin"})
    with pytest.raises(HTTPException) as info:
        user_from_claims(creds)
    assert info.value.status_code == 401


def test_require_admin():
    assert require_admin(UserContext(user_id="u", role="admin")).role == "admin"
    with pytest.raises(HTTPException) as info:
        require_admin(UserContext(user_id="u", role="student"))
    assert info.value.status_code == 403


def test_a_guard_is_built_only_when_a_jwks_url_is_configured():
    assert make_clerk_guard(None) is None
    guard = make_clerk_guard("https://example.clerk.accounts.dev/.well-known/jwks.json")
    assert guard is not None and guard.jwks_url.endswith("jwks.json")


JWKS_URL = "https://example.clerk.accounts.dev/.well-known/jwks.json"


@pytest.fixture
def guarded_client(db, make_container):
    """An app with a guard configured. No token is ever valid against this JWKS url - the point
    is what the API answers when credentials are missing or cannot be verified."""
    app = create_app(make_container(clerk_jwks_url=JWKS_URL))
    return TestClient(app)


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-header"),
        pytest.param({"Authorization": "Basic dXNlcjpwYXNz"}, id="wrong-scheme"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed-bearer"),
        pytest.param({"Authorization": "Bearer"}, id="scheme-without-credentials"),
    ],
)
def test_authentication_failures_answer_401_with_our_error_body(guarded_client, headers):
    response = guarded_client.get("/api/subjects", headers=headers)
    assert response.status_code == 401, response.text
    body = response.json()
    assert set(body) == {"detail"} and body["detail"] == "missing or invalid credentials"
    assert ErrorResponse(**body).detail == "missing or invalid credentials"
