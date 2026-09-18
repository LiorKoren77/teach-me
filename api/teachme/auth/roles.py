from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from teachme.auth.clerk import ADMIN, CurrentUser, UserContext, require_role


def require_admin(user: CurrentUser) -> UserContext:
    """Admin routes are read-only, but they read every subject and every price, so the role is
    checked here rather than route by route."""
    return require_role(user, ADMIN)


AdminUser = Annotated[UserContext, Depends(require_admin)]
