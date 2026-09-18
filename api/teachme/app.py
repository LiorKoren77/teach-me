from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from teachme.adapters.db.migrate import ensure_schema_current
from teachme.auth.clerk import make_clerk_guard
from teachme.container import Container
from teachme.routes import admin, admin_sources, jobs, learning, pages, subjects
from teachme.routes.errors import install_error_handlers

UPLOAD_PATH = re.compile(r"^/api/admin/subjects/[^/]+/sources/?$")


class RefuseOversizedUploads:
    """Answers 413 to an upload that declares more bytes than MAX_UPLOAD_BYTES, before anything
    reads its body.

    It has to sit out here because FastAPI parses the whole multipart form before the endpoint's
    first line runs: a check inside the endpoint has already paid for the upload, and a body that
    is oversized *and* malformed never reaches the check at all - the parser answers 400 first,
    which is the wrong thing to tell a client whose file is simply too big. A chunked body
    declares no length, so there is nothing to test here and the endpoint's own byte check stays
    as the guard for those."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self._app = app
        self._limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._is_an_upload(scope):
            declared = Headers(scope=scope).get("content-length")
            if declared and declared.isdigit() and int(declared) > self._limit:
                response = JSONResponse(
                    {"detail": f"upload is larger than the {self._limit} byte limit"},
                    status_code=413,
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)

    @staticmethod
    def _is_an_upload(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and UPLOAD_PATH.match(scope.get("path", "")) is not None
        )


def create_app(container: Container | None = None) -> FastAPI:
    """The whole HTTP surface. A container passed in (tests, a local run) is used as it is and
    left to its owner to close; without one the app builds and owns its own."""
    owned = container is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            # A database that is behind the code would break per request, one missing column at a
            # time; the error is let through so the app fails to start instead of serving. The
            # check runs on a pooled connection - the same connections the requests will use -
            # and never on the container's single CLI connection.
            with app.state.container.pool.connection() as conn:
                ensure_schema_current(conn)
            yield
        finally:
            if owned:
                app.state.container.close()

    app = FastAPI(title="teach-me", lifespan=lifespan)
    # Set before the lifespan runs, so a TestClient used without its context manager - and a
    # health check that arrives before startup finishes - still finds the container.
    app.state.container = container or Container()
    app.state.clerk_guard = make_clerk_guard(app.state.container.settings.clerk_jwks_url)
    app.add_middleware(RefuseOversizedUploads, limit=app.state.container.settings.max_upload_bytes)
    install_error_handlers(app)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "teach-me"}

    app.include_router(subjects.router)
    app.include_router(pages.router)
    app.include_router(learning.router)
    app.include_router(admin.router)
    app.include_router(admin_sources.router)
    app.include_router(jobs.router)
    return app
