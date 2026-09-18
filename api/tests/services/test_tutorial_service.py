from __future__ import annotations

import pytest

from teachme.container import Container
from teachme.domain.models import ContentStatus, SubjectState
from teachme.generation.errors import SubjectNotReady
from teachme.ingestion.bundle import bundle_slug
from teachme.ingestion.errors import SubjectLocked
from teachme.repositories.usage import UsageRepository
from teachme.settings import Settings
from tests.helpers import make_pdf


@pytest.fixture
def container(db, migrated_database, tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=migrated_database,
        llm_provider="fake",
        embeddings_provider="fake",
        reranker_provider="noop",
        file_store="local",
        local_files_dir=tmp_path / "files",
        digest_dir=tmp_path / "digest",
        pages_per_read_batch=3,
        pages_per_chunk_batch=3,
    )
    c = Container(settings)
    yield c
    c.close()


def _ingested_subject(c, name="Geo", languages=("he", "en"), pages=6):
    subject = c.subject_service.get_or_create(name, list(languages))
    source = c.source_service.register(subject, "ch1.pdf", make_pdf(pages))
    c.pipeline.ingest_source(source.id)
    return c.subjects.get(subject.id)


def test_generate_requires_ready_sources(container):
    subject = container.subject_service.get_or_create("Empty", ["he"])
    with pytest.raises(SubjectNotReady):
        container.tutorial_service.generate(subject)


def test_generate_creates_outline_glossary_content_and_questions_for_every_language(container):
    subject = _ingested_subject(container)
    report = container.tutorial_service.generate(subject)
    assert report.outline_version == 1 and report.new_outline
    assert report.failures == []
    languages = {r.language for r in report.results}
    assert languages == {"he", "en"}
    outline = container.outlines.latest(subject.id)
    parts = container.outlines.parts(outline.id)
    assert len(parts) >= 2
    for part in parts:
        for language in ("he", "en"):
            content = container.content.part(part.id, language)
            assert content is not None and content.status == ContentStatus.READY
            assert len(container.questions.for_part(part.id, language)) >= 5
    assert {t.slug for t in container.glossary.terms(outline.id)} == {"biosphere", "atmosphere"}
    assert len(container.glossary.translations(outline.id, "he")) == 2

    slug = bundle_slug(subject.name, subject.id)
    keys = container.bundle_stores[0].list_keys(f"{slug}/")
    assert f"{slug}/outline.json" in keys and f"{slug}/glossary.he.json" in keys
    assert f"{slug}/parts/01.he.md" in keys and f"{slug}/questions.en.jsonl" in keys

    purposes = {row["purpose"] for row in UsageRepository(container.conn).summarize(subject_id=subject.id)}
    assert {
        "gen.outline",
        "gen.glossary",
        "gen.glossary_translate",
        "gen.teaching",
        "gen.questions",
    } <= purposes


def test_status_publish_and_unpublish(container):
    subject = _ingested_subject(container)
    status = container.tutorial_service.status(subject)
    assert status.outline_version is None and not status.publishable
    with pytest.raises(SubjectNotReady):
        container.tutorial_service.publish(subject)

    container.tutorial_service.generate(subject)
    status = container.tutorial_service.status(subject)
    assert status.publishable and all(lang.complete for lang in status.languages)

    published = container.tutorial_service.publish(subject)
    assert published.state == SubjectState.PUBLISHED and published.current_outline_version == 1
    with pytest.raises(SubjectLocked):
        container.tutorial_service.generate(published)

    draft = container.tutorial_service.unpublish(published)
    assert draft.state == SubjectState.DRAFT and draft.current_outline_version == 1


def test_regenerate_creates_new_version_and_content_only_reuses_it(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    report = container.tutorial_service.generate(subject, languages=["he"], content_only=True)
    assert report.outline_version == 1 and not report.new_outline
    assert {r.language for r in report.results} == {"he"}
    report = container.tutorial_service.generate(subject)
    assert report.outline_version == 2 and report.new_outline


def test_publish_notifies_version_listeners_only_on_change(container):
    subject = _ingested_subject(container)
    seen = []
    container.tutorial_service.on_version_published(lambda subj, version: seen.append(version))
    container.tutorial_service.generate(subject)
    container.tutorial_service.publish(subject)
    container.tutorial_service.unpublish(container.subjects.get(subject.id))
    container.tutorial_service.publish(container.subjects.get(subject.id))
    assert seen == [1]


def test_rendered_part_resolves_placeholders_with_source_gloss(container):
    subject = _ingested_subject(container)  # fake detects language "en"; teaching in "he" is cross-language
    container.tutorial_service.generate(subject)
    rendered = container.tutorial_service.rendered_part(subject, "he", part_position=0)
    assert "{{term:" not in rendered.body
    assert "fake-words (biosfera)" in rendered.body or "fake-words (atmosfera)" in rendered.body
    assert rendered.title == "Fake part title" and rendered.sections
    same_language = container.tutorial_service.rendered_part(subject, "en", part_position=0)
    assert "(biosfera)" not in same_language.body
