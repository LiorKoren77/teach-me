from __future__ import annotations

from uuid import uuid4

import pytest

from teachme.domain.models import SourceStatus, SubjectState
from teachme.repositories.errors import SourceNotFound, SubjectNotFound
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository


def test_subject_create_get_list(db):
    repo = SubjectRepository(db)
    subject = repo.create("History ch. 3", ["he", "en"], created_by="user_1")
    assert subject.state == SubjectState.DRAFT
    assert subject.languages == ("he", "en")
    assert repo.get(subject.id) == subject
    assert repo.get_by_name("History ch. 3") == subject
    assert repo.get_by_name("nope") is None
    assert [s.name for s in repo.list()] == ["History ch. 3"]


def test_subject_set_state_and_missing(db):
    repo = SubjectRepository(db)
    subject = repo.create("Geo", ["pt"])
    repo.set_state(subject.id, SubjectState.PUBLISHED)
    assert repo.get(subject.id).state == SubjectState.PUBLISHED
    with pytest.raises(SubjectNotFound):
        repo.get(uuid4())


def test_source_lifecycle(db):
    subject = SubjectRepository(db).create("Physics", ["en"])
    repo = SourceRepository(db)
    source = repo.create(subject.id, "ch1.pdf", "application/pdf", "sources/x/ch1.pdf", 1234)
    assert source.status == SourceStatus.UPLOADED
    repo.set_status(source.id, SourceStatus.EXTRACTING)
    repo.set_extraction_result(source.id, page_count=12, vision_pages=12, detected_language="pt")
    repo.set_status(source.id, SourceStatus.FAILED, error="boom", resume_status=SourceStatus.CHUNKING)
    loaded = repo.get(source.id)
    assert loaded.page_count == 12 and loaded.detected_language == "pt"
    assert loaded.status == SourceStatus.FAILED and loaded.resume_status == SourceStatus.CHUNKING
    assert loaded.error == "boom"
    repo.set_status(source.id, SourceStatus.READY)
    assert repo.get(source.id).error is None and repo.get(source.id).resume_status is None
    assert [s.id for s in repo.list_by_subject(subject.id)] == [source.id]
    repo.delete(source.id)
    with pytest.raises(SourceNotFound):
        repo.get(source.id)
