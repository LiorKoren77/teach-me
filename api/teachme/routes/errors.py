from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from teachme.domain.assessment.scoring import UnmappedQuestion
from teachme.domain.assessment.transitions import IllegalTransition
from teachme.generation.errors import GenerationError
from teachme.ingestion.errors import SubjectLocked
from teachme.repositories.errors import NotFound
from teachme.routes.schemas import ErrorResponse
from teachme.services.learning import LearningError, NotAllowed, RateLimited

# Starlette looks a handler up along the exception's MRO, so the most specific class registered
# wins: RateLimited before NotAllowed, NotAllowed before LearningError.
STATUS_BY_ERROR: tuple[tuple[int, type[Exception]], ...] = (
    (404, NotFound),
    (403, NotAllowed),
    (429, RateLimited),
    (409, LearningError),
    (409, IllegalTransition),
    (409, UnmappedQuestion),
    (409, GenerationError),
    (409, SubjectLocked),
)


def install_error_handlers(app: FastAPI) -> None:
    """Domain refusals become status codes with a message we wrote. Anything not listed here is
    a bug, and stays a 500 with no detail rather than leaking internals to the client."""

    def handler(status_code: int):
        async def handle(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(
                status_code=status_code,
                content=ErrorResponse(detail=str(exc)).model_dump(),
            )

        return handle

    for status_code, error in STATUS_BY_ERROR:
        app.add_exception_handler(error, handler(status_code))
