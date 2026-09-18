from __future__ import annotations

from pathlib import Path

from teachme.adapters.identity import IdentityUnavailable


class FileIdentity:
    """The `identity_token_provider` for a token that arrives as a file: a Kubernetes projected
    service-account token, an IRSA web-identity token, or a file an operator writes for a local
    run against federation.

    Read fresh on every call, never cached: these files are rotated in place, so a token read
    once and kept would go on being presented after it expired."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def __call__(self) -> str:
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise IdentityUnavailable(f"identity token file {self._path} could not be read: {exc}") from exc
        token = content.strip()
        if not token:
            raise IdentityUnavailable(f"identity token file {self._path} is empty")
        return token
