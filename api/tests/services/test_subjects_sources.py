from __future__ import annotations

import pytest

from teachme.adapters.chunk_search.memory import InMemoryChunkSearch
from teachme.adapters.file_store.memory import InMemoryFileStore
from teachme.adapters.llm.anthropic import AnthropicLLM
from teachme.adapters.llm.fake import FakeLLM
from teachme.domain.models import SourceStatus, SubjectState
from teachme.ingestion.errors import SubjectLocked, UnsupportedMediaType
from teachme.repositories.errors import SubjectNotFound
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.services.sources import SourceService
from teachme.services.subjects import LanguageNotEnabled, SubjectService
from teachme.settings import Settings
from tests.helpers import make_pdf


@pytest.fixture
def services(db):
    settings = Settings(_env_file=None, llm_provider="fake")
    subjects = SubjectRepository(db)
    files = InMemoryFileStore()
    search = InMemoryChunkSearch()
    subject_service = SubjectService(db, subjects, settings)
    source_service = SourceService(db, settings, FakeLLM({}), files, search, SourceRepository(db), subjects)
    return subject_service, source_service, files, search


def test_subject_get_or_create_and_language_check(services):
    subject_service, *_ = services
    a = subject_service.get_or_create("Geo", ["he", "pt"])
    assert a.languages == ("he", "pt") and a.state == SubjectState.DRAFT
    assert subject_service.get_or_create("Geo") == a
    assert subject_service.require("Geo") == a
    with pytest.raises(SubjectNotFound):
        subject_service.require("Nope")
    with pytest.raises(LanguageNotEnabled):
        subject_service.get_or_create("Chem", ["fr"])


def test_source_register_validates_type_and_stores_file(services):
    subject_service, source_service, files, _ = services
    subject = subject_service.get_or_create("Geo")
    assert source_service.media_type_for("notes.md") == "text/markdown"
    assert source_service.media_type_for("ch1.PDF") == "application/pdf"
    assert source_service.media_type_for("weird.xyz") is None
    source = source_service.register(subject, "ch1.pdf", make_pdf(1))
    assert source.status == SourceStatus.UPLOADED and files.exists(source.file_key)
    assert [s.id for s in source_service.list(subject)] == [source.id]
    with pytest.raises(UnsupportedMediaType):
        source_service.register(subject, "archive.zip", b"PK")


def test_media_type_for_webp_and_gzipped_files():
    assert SourceService.media_type_for("a.webp") == "image/webp"
    assert SourceService.media_type_for("doc.pdf.gz") is None


def test_media_type_for_covers_every_llm_capability():
    extensions = [".pdf", ".png", ".jpg", ".gif", ".webp", ".txt", ".md"]
    produced = {SourceService.media_type_for(f"file{ext}") for ext in extensions}
    for media_type in AnthropicLLM.MEDIA_TYPES:
        assert media_type in produced


def test_settings_can_narrow_accepted_types(db):
    settings = Settings(_env_file=None, llm_provider="fake", allowed_upload_types=["application/pdf"])
    subjects = SubjectRepository(db)
    service = SourceService(
        db, settings, FakeLLM({}), InMemoryFileStore(), InMemoryChunkSearch(), SourceRepository(db), subjects
    )
    assert service.accepted_media_types() == frozenset({"application/pdf"})


def test_delete_and_reingest_respect_publish_lock(services):
    subject_service, source_service, files, search = services
    subject = subject_service.get_or_create("Geo")
    source = source_service.register(subject, "ch1.pdf", make_pdf(1))
    source_service.mark_for_reingest(source.id)
    subject_service.set_state(subject, SubjectState.PUBLISHED)
    with pytest.raises(SubjectLocked):
        source_service.delete(source.id)
    subject_service.set_state(subject, SubjectState.DRAFT)
    source_service.delete(source.id)
    assert not files.exists(source.file_key) and source_service.list(subject) == []
