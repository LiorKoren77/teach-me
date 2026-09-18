from __future__ import annotations

from typing import Protocol


class FileNotFound(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"no file at key {key!r}")
        self.key = key


class FileStore(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes:
        """Raises FileNotFound."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None:
        """Idempotent: deleting a missing key is not an error."""
        ...

    def list_keys(self, prefix: str) -> list[str]:
        """Every key starting with prefix, sorted."""
        ...
