from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from teachme.adapters.db.migrate import ensure_schema_current
from teachme.auth.clerk import make_clerk_guard
from teachme.container import Container
from teachme.routes import admin, admin_sources, jobs, learning, pages, subjects
from teachme.routes.errors import install_error_handlers


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
