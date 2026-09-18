from __future__ import annotations

from contextvars import ContextVar, Token

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from teachme.adapters.identity import IdentityUnavailable

# Vercel signs one of these per invocation and puts it on the incoming request. It is the
# deployment's own identity - project, environment, team - not the caller's.
OIDC_HEADER = "x-vercel-oidc-token"

_current_token: ContextVar[str | None] = ContextVar("vercel_oidc_token", default=None)


def set_request_token(token: str | None) -> Token[str | None]:
    return _current_token.set(token)


def reset_request_token(reset: Token[str | None]) -> None:
    _current_token.reset(reset)


def current_token() -> str | None:
    """The token of the request being served on this task, if any."""
    return _current_token.get()


class CarryVercelOidcToken:
    """Copies the deployment's OIDC token off the request and puts it where the LLM adapter's
    credentials provider can reach it, then takes it away again.

    A context variable rather than an argument threaded through every call site: the token is
    read deep inside the Anthropic SDK, when it decides an access token has expired, and only it
    knows when that is. Each request is served on its own task, so one request never sees
    another's token; the reset in `finally` is what keeps a token from outliving the request that
    carried it - a later request without the header would otherwise present it as its own."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        reset = set_request_token(Headers(scope=scope).get(OIDC_HEADER))
        try:
            await self._app(scope, receive, send)
        finally:
            reset_request_token(reset)


class VercelOidcIdentity:
    """The `identity_token_provider` a deployment running on Vercel hands the SDK: zero
    arguments, called whenever a new access token has to be minted, and answering with the token
    of the request in flight.

    Outside a request there is nothing to answer with - a CLI run, a worker loop, a background
    thread - so it refuses by name rather than exchanging an empty assertion. Those runs
    authenticate with IDENTITY_PROVIDER=file or an API key."""

    def __call__(self) -> str:
        token = current_token()
        if not token:
            raise IdentityUnavailable(
                f"no {OIDC_HEADER} on the request being served: IDENTITY_PROVIDER=vercel_oidc only"
                " works inside a Vercel request. Use IDENTITY_PROVIDER=file (with"
                " IDENTITY_TOKEN_FILE) or ANTHROPIC_API_KEY for a CLI or worker run."
            )
        return token
