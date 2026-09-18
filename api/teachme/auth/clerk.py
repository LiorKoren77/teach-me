from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict

STUDENT = "student"
ADMIN = "admin"


class UserContext(BaseModel):
    """Who is calling, as far as the API is concerned: nothing but the verified claims."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    role: str = STUDENT


def user_from_claims(creds: Any) -> UserContext:
    """Clerk session token: `sub` is the user id; the role comes from a `role` claim that the
    Clerk session-token template maps from `public_metadata.role` (falls back to student)."""
    decoded = getattr(creds, "decoded", None) or {}
    user_id = decoded.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="token carries no subject")
    role = decoded.get("role") or (decoded.get("public_metadata") or {}).get("role") or STUDENT
    return UserContext(user_id=str(user_id), role=str(role))


async def current_user(request: Request) -> UserContext:
    """The only place a request turns into a user. Tests and local runs override this dependency
    instead of minting Clerk tokens, so no test ever reaches Clerk."""
    guard: ClerkHTTPBearer | None = getattr(request.app.state, "clerk_guard", None)
    if guard is None:
        raise HTTPException(status_code=503, detail="authentication is not configured")
    creds: HTTPAuthorizationCredentials | None = await guard(request)
    if creds is None or creds.decoded is None:
        raise HTTPException(status_code=401, detail="missing or invalid credentials")
    return user_from_claims(creds)


def make_clerk_guard(jwks_url: str | None) -> ClerkHTTPBearer | None:
    """No JWKS url configured (the fake stack, a local run) means no guard: `current_user` then
    refuses every request unless the dependency is overridden."""
    return ClerkHTTPBearer(ClerkConfig(jwks_url=jwks_url)) if jwks_url else None


CurrentUser = Annotated[UserContext, Depends(current_user)]


def require_role(user: UserContext, role: str) -> UserContext:
    if user.role != role:
        raise HTTPException(status_code=403, detail=f"{role} role required")
    return user
