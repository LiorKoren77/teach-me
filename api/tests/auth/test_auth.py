from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from teachme.auth.clerk import UserContext, make_clerk_guard, user_from_claims
from teachme.auth.roles import require_admin


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
