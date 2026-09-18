from __future__ import annotations

from vercel.blob import BlobClient
from vercel.blob.errors import BlobNotFoundError

from teachme.ports.file_store import FileNotFound


class VercelBlobFileStore:
    """Private blobs under a fixed prefix. Token from BLOB_READ_WRITE_TOKEN unless given."""

    name = "vercel_blob"

    def __init__(self, prefix: str, token: str | None = None, client: BlobClient | None = None) -> None:
        self._prefix = prefix.strip().strip("/")
        if not self._prefix:
            raise ValueError("VercelBlobFileStore requires a non-empty prefix")
        self._client = client or BlobClient(token=token)

    def _path(self, key: str) -> str:
        return f"{self._prefix}/{key}"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put(self._path(key), data, access="private", content_type=content_type, overwrite=True)

    def get(self, key: str) -> bytes:
        try:
            result = self._client.get(self._path(key), access="private")
        except BlobNotFoundError as exc:
            raise FileNotFound(key) from exc
        if result is None or result.status_code != 200:
            raise FileNotFound(key)
        return bytes(result.content)

    def exists(self, key: str) -> bool:
        try:
            self._client.head(self._path(key))
            return True
        except BlobNotFoundError:
            return False

    def delete(self, key: str) -> None:
        try:
            self._client.delete(self._path(key))
        except BlobNotFoundError:
            return

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        cursor = None
        full_prefix = self._path(prefix)
        while True:
            page = self._client.list_objects(prefix=full_prefix, cursor=cursor, limit=1000)
            keys.extend(item.pathname[len(self._prefix) + 1 :] for item in page.blobs)
            if not page.has_more:
                break
            cursor = page.cursor
        return sorted(keys)
