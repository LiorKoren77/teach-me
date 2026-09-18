from __future__ import annotations

from teachme.ports.file_store import FileStore


class PrefixedFileStore:
    """View of another store under a fixed key prefix. Lets the digest bundle live at
    digest/... in the primary store while bundle code sees plain relative keys."""

    def __init__(self, inner: FileStore, prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix
        self.name = f"{inner.name}:{prefix}"

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._inner.put(self._key(key), data, content_type)

    def get(self, key: str) -> bytes:
        return self._inner.get(self._key(key))

    def exists(self, key: str) -> bool:
        return self._inner.exists(self._key(key))

    def delete(self, key: str) -> None:
        self._inner.delete(self._key(key))

    def list_keys(self, prefix: str) -> list[str]:
        return [k[len(self._prefix) :] for k in self._inner.list_keys(self._key(prefix))]
