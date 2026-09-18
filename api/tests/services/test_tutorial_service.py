from __future__ import annotations

import json

import pytest

from teachme.container import Container
from teachme.domain.models import ContentStatus, SubjectState
from teachme.generation.errors import GenerationError, SubjectNotReady
from teachme.generation.fake_responders import default_responders
from teachme.generation.glossary import GlossaryOut
from teachme.generation.question_bank import QuestionBankOut
from teachme.generation.teaching import TeachingOut
from teachme.ingestion.bundle import bundle_slug
from teachme.ingestion.errors import SubjectLocked
from teachme.ports.llm import LLMError
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
    assert f"{slug}/v1/outline.json" in keys and f"{slug}/v1/glossary.he.json" in keys
    assert f"{slug}/v1/parts/01.he.md" in keys and f"{slug}/v1/questions.en.jsonl" in keys

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


def test_a_failed_part_is_reported_and_leaves_nothing_behind(container):
    subject = _ingested_subject(container)

    def boom(request):
        raise LLMError("question service down")

    container.llm.inner.set_responder(QuestionBankOut, boom)
    report = container.tutorial_service.generate(subject)
    assert report.failures

    outline = container.outlines.latest(subject.id)
    parts = container.outlines.parts(outline.id)
    for part in parts:
        for language in ("he", "en"):
            content = container.content.part(part.id, language)
            assert content is not None and content.status == ContentStatus.FAILED
            assert container.content.sections(part.id, language) == []
            assert container.questions.for_part(part.id, language) == []

    slug = bundle_slug(subject.name, subject.id)
    store = container.bundle_stores[0]
    part_keys = [key for key in store.list_keys(f"{slug}/") if "/parts/" in key]
    assert len(part_keys) == len(parts) * 2  # a failed stub per part per language, no ready content
    for key in part_keys:
        stub = store.get(key).decode()
        assert "status=failed" in stub and "#" not in stub
    assert container.tutorial_service.status(subject).publishable is False


def test_failed_part_regeneration_clears_the_previous_attempts_content(container):
    subject = _ingested_subject(container, pages=9)  # several parts, so other parts stay untouched
    container.tutorial_service.generate(subject)
    outline = container.outlines.latest(subject.id)
    part = next(p for p in container.outlines.parts(outline.id) if p.position == 0)
    before_questions = container.tutorial_service.status(subject).languages
    he_before = next(lang for lang in before_questions if lang.language == "he").questions

    def boom(request):
        raise LLMError("teaching service down")

    container.llm.inner.set_responder(TeachingOut, boom)
    report = container.tutorial_service.generate(subject, languages=["he"], parts=[0])
    assert report.failures and report.results[0].content_status == ContentStatus.FAILED

    content = container.content.part(part.id, "he")
    assert content is not None and content.status == ContentStatus.FAILED
    assert container.content.sections(part.id, "he") == []
    assert container.questions.for_part(part.id, "he") == []

    status = container.tutorial_service.status(subject)
    he_after = next(lang for lang in status.languages if lang.language == "he")
    assert he_after.questions < he_before

    slug = bundle_slug(subject.name, subject.id)
    store = container.bundle_stores[0]
    stub = store.get(f"{slug}/v1/parts/01.he.md").decode()
    assert "status=failed" in stub and "teaching service down" in stub and "#" not in stub

    jsonl = store.get(f"{slug}/v1/questions.he.jsonl").decode()
    assert all(json.loads(line)["part_position"] != 0 for line in jsonl.splitlines() if line)


def test_a_glossary_failure_leaves_no_new_outline_version(container):
    subject = _ingested_subject(container)

    def boom(request):
        raise LLMError("glossary service down")

    container.llm.inner.set_responder(GlossaryOut, boom)
    with pytest.raises(LLMError):
        container.tutorial_service.generate(subject)
    assert container.outlines.latest(subject.id) is None


def test_per_part_regeneration_reuses_the_current_outline_version(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    report = container.tutorial_service.generate(subject, parts=[0])
    assert report.outline_version == 1 and not report.new_outline
    assert {r.part_position for r in report.results} == {0}
    assert container.tutorial_service.status(subject).publishable


def test_generate_rejects_unknown_part_positions(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    with pytest.raises(GenerationError, match=r"no such parts: \[9\]"):
        container.tutorial_service.generate(subject, parts=[9])
    assert container.outlines.latest(subject.id).version == 1


def test_generate_rejects_part_selection_before_any_outline_exists(container):
    subject = _ingested_subject(container)
    with pytest.raises(GenerationError, match="no such parts"):
        container.tutorial_service.generate(subject, parts=[0])
    assert container.outlines.latest(subject.id) is None


def test_publish_picks_the_newest_complete_version(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    assert container.tutorial_service.status(subject).publishable

    teaching = default_responders()[TeachingOut]

    def fail_in_english(request):
        text = "\n".join(part.text or "" for part in request.parts if part.kind == "text")
        if "LANGUAGE: en" in text:
            raise LLMError("teaching service down")
        return teaching(request)

    container.llm.inner.set_responder(TeachingOut, fail_in_english)
    report = container.tutorial_service.generate(subject)
    assert report.outline_version == 2 and report.failures
    assert not container.tutorial_service.status(subject).publishable

    published = container.tutorial_service.publish(subject)
    assert published.state == SubjectState.PUBLISHED and published.current_outline_version == 1


def test_status_reports_the_version_publish_would_select(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    assert container.tutorial_service.status(subject).publishable_version == 1

    teaching = default_responders()[TeachingOut]

    def fail_in_english(request):
        text = "\n".join(part.text or "" for part in request.parts if part.kind == "text")
        if "LANGUAGE: en" in text:
            raise LLMError("teaching service down")
        return teaching(request)

    container.llm.inner.set_responder(TeachingOut, fail_in_english)
    report = container.tutorial_service.generate(subject)
    assert report.outline_version == 2 and report.failures

    status = container.tutorial_service.status(subject)
    assert status.outline_version == 2
    assert status.publishable is False
    assert status.publishable_version == 1


def test_status_reports_per_part_readiness_and_failed_parts(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)

    def boom(request):
        raise LLMError("teaching service down")

    container.llm.inner.set_responder(TeachingOut, boom)
    container.tutorial_service.generate(subject, languages=["he"], parts=[0])

    status = container.tutorial_service.status(subject)
    he = next(lang for lang in status.languages if lang.language == "he")
    en = next(lang for lang in status.languages if lang.language == "en")
    assert he.parts_ready == he.parts_total - 1 and not he.complete and he.failed == (0,)
    assert en.parts_ready == en.parts_total and en.complete and en.failed == ()
    assert not status.publishable


def test_rendered_part_treats_published_version_zero_as_missing(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    zeroed = subject.model_copy(update={"current_outline_version": 0})
    with pytest.raises(SubjectNotReady, match="no outline"):
        container.tutorial_service.rendered_part(zeroed, "he", part_position=0)


def test_rendered_part_can_render_the_latest_draft_version(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    published = container.tutorial_service.publish(subject)
    container.tutorial_service.unpublish(published)
    container.tutorial_service.generate(container.subjects.get(subject.id), languages=["he"])
    subject = container.tutorial_service.publish(container.subjects.get(subject.id))
    assert subject.current_outline_version == 1

    rendered = container.tutorial_service.rendered_part(subject, "he", part_position=0)
    assert rendered.outline_version == 1 and rendered.published
    draft = container.tutorial_service.rendered_part(subject, "he", part_position=0, draft=True)
    assert draft.outline_version == 2 and not draft.published


def test_a_draft_regeneration_does_not_overwrite_the_published_version_bundle(container):
    subject = _ingested_subject(container, languages=("he",))
    container.tutorial_service.generate(subject)
    container.tutorial_service.publish(subject)
    container.tutorial_service.unpublish(container.subjects.get(subject.id))

    slug = bundle_slug(subject.name, subject.id)
    store = container.bundle_stores[0]
    published_part = store.get(f"{slug}/v1/parts/01.he.md")

    container.tutorial_service.generate(container.subjects.get(subject.id))
    keys = store.list_keys(f"{slug}/")
    assert f"{slug}/v2/outline.json" in keys and f"{slug}/v2/parts/01.he.md" in keys
    assert store.get(f"{slug}/v1/parts/01.he.md") == published_part
