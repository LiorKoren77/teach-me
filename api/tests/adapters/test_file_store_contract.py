from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws

from teachme.adapters.file_store.local import LocalFileStore
from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.adapters.file_store.s3 import S3FileStore
from teachme.adapters.file_store.vercel_blob import VercelBlobFileStore
from teachme.ports.file_store import FileNotFound


@pytest.fixture(params=["memory", "local", "s3", "vercel_blob"])
def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryFileStore()
    elif request.param == "local":
        yield LocalFileStore(tmp_path / "files")
    elif request.param == "s3":
        with mock_aws():
            client = boto3.client("s3", region_name="eu-central-1")
            client.create_bucket(
                Bucket="teachme-test", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"}
            )
            yield S3FileStore(bucket="teachme-test", region="eu-central-1", client=client)
    else:
        if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
            pytest.skip("BLOB_READ_WRITE_TOKEN not set")
        blob = VercelBlobFileStore(prefix=f"teach-me-test/{os.getpid()}")
        yield blob
        for key in blob.list_keys(""):
            blob.delete(key)


def test_put_get_exists(store):
    store.put("a/b.txt", b"hi", "text/plain")
    assert store.get("a/b.txt") == b"hi"
    assert store.exists("a/b.txt")
    assert not store.exists("a/missing.txt")


def test_get_missing_raises(store):
    with pytest.raises(FileNotFound):
        store.get("nope/none.bin")


def test_overwrite_replaces_content(store):
    store.put("k.txt", b"one", "text/plain")
    store.put("k.txt", b"two", "text/plain")
    assert store.get("k.txt") == b"two"


def test_delete_is_idempotent(store):
    store.put("d.txt", b"x", "text/plain")
    store.delete("d.txt")
    store.delete("d.txt")
    assert not store.exists("d.txt")


def test_list_keys_by_prefix_sorted(store):
    store.put("p/2.md", b"2", "text/markdown")
    store.put("p/1.md", b"1", "text/markdown")
    store.put("q/1.md", b"1", "text/markdown")
    assert store.list_keys("p/") == ["p/1.md", "p/2.md"]
    assert store.list_keys("zzz/") == []


@pytest.mark.parametrize("key", ["../escape.txt", "a/../../escape.txt", "/etc/passwd"])
def test_local_store_rejects_escaping_key(tmp_path, key):
    store = LocalFileStore(tmp_path / "files")
    with pytest.raises(ValueError):
        store.put(key, b"x", "text/plain")


def test_vercel_blob_requires_a_prefix():
    with pytest.raises(ValueError):
        VercelBlobFileStore(prefix="  ", client=object())
