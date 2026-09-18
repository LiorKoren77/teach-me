from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from teachme.container import Container
from teachme.scope import Scope


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_scope(request: Request) -> Iterator[Scope]:
    """One pooled connection per request, returned on every exit path - a handled error, an
    unhandled one, and a client that disconnects in the middle of a stream."""
    with get_container(request).request_scope() as scope:
        yield scope


ScopeDep = Annotated[Scope, Depends(get_scope)]
