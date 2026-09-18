from __future__ import annotations

from pathlib import Path

from teachme.ports.file_store import FileNotFound


class LocalFileStore:
    """Keys map to paths under root. Used for development and for the local digest bundle."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root.resolve() not in path.parents and path != self._root.resolve():
            raise ValueError(f"key escapes the store root: {key!r}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFound(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def list_keys(self, prefix: str) -> list[str]:
        root = self._root.resolve()
        if not root.exists():
            return []
        keys = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
        return sorted(k for k in keys if k.startswith(prefix))
