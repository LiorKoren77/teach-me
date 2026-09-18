from __future__ import annotations

from teachme.ports.file_store import FileNotFound


class InMemoryFileStore:
    name = "memory"

    def __init__(self) -> None:
        self._files: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._files[key] = (bytes(data), content_type)

    def get(self, key: str) -> bytes:
        try:
            return self._files[key][0]
        except KeyError as exc:
            raise FileNotFound(key) from exc

    def exists(self, key: str) -> bool:
        return key in self._files

    def delete(self, key: str) -> None:
        self._files.pop(key, None)

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self._files if k.startswith(prefix))
