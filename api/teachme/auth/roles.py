from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from teachme.auth.clerk import ADMIN, CurrentUser, UserContext, require_role


def require_admin(user: CurrentUser) -> UserContext:
    """Admin routes read every subject and every price, and change what a subject teaches -
    upload, delete, reingest, generate, publish - so the role is checked here, once, rather than
    route by route."""
    return require_role(user, ADMIN)


AdminUser = Annotated[UserContext, Depends(require_admin)]
