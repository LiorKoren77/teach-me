from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

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
from teachme.services.generation_jobs import (
    GENERATE_SUBJECT,
    GENERATE_UNIT,
    GenerateSubjectJob,
    GenerateUnitJob,
)
from teachme.services.tutorial import GenerationUnit, UnitKind
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


def test_rendered_part_carries_the_page_refs_the_teaching_text_points_at(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    outline = container.outlines.latest(subject.id)
    part = next(p for p in container.outlines.parts(outline.id) if p.position == 0)
    # generate -> repository: the stored content keeps the indices the generator returned
    stored = container.content.part(part.id, "he")
    assert stored is not None and stored.page_refs == (part.page_start,)
    # repository -> rendered_part: they reach the client as global corpus indices, which is what
    # GET /api/subjects/{id}/pages/{global_index}/image takes
    rendered = container.tutorial_service.rendered_part(subject, "he", part_position=0)
    assert rendered.page_refs == (part.page_start,)


def test_rendered_part_labels_every_page_ref_with_its_printed_number(container):
    subject = _ingested_subject(container)
    source = container.sources.list_by_subject(subject.id)[0]
    # A scanned book: the first page is an unnumbered cover, the rest carry printed numbers that
    # do not line up with the corpus indices at all - which is exactly why the label is needed.
    stored = container.pages.list(source.id)
    container.pages.replace(
        source.id,
        [
            page.model_copy(update={"printed_number": None if i == 0 else str(11 + i)})
            for i, page in enumerate(stored)
        ],
    )
    container.conn.commit()
    container.tutorial_service.generate(subject)

    outline = container.outlines.latest(subject.id)
    seen: list[str] = []
    for part in container.outlines.parts(outline.id):
        rendered = container.tutorial_service.rendered_part(subject, "he", part_position=part.position)
        assert rendered.page_refs  # the fake generator points at the part's first page
        assert rendered.page_labels == tuple(
            "" if index == 0 else str(11 + index) for index in rendered.page_refs
        )
        seen.extend(rendered.page_labels)
    assert "" in seen  # the cover: a page without a printed number is labelled with nothing
    assert any(label for label in seen)


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


def test_plan_generation_puts_the_outline_first_then_one_unit_per_part_and_language(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    outline = container.outlines.latest(subject.id)
    parts = container.outlines.parts(outline.id)

    units = container.tutorial_service.plan_generation(subject, content_only=True)
    assert units[0].kind is UnitKind.OUTLINE and not units[0].new_outline
    assert units[0].languages == ("he", "en")
    assert len(units) == 1 + len(parts) * 2
    assert [(u.kind, u.language, u.part_position) for u in units[1:]] == [
        (UnitKind.PART, language, part.position) for language in ("he", "en") for part in parts
    ]
    assert all(u.outline_version == outline.version for u in units[1:])

    # A run that will create a new version cannot name its parts yet - they do not exist. The plan
    # stops at the outline unit; running it is what makes the parts plannable.
    fresh = container.tutorial_service.plan_generation(subject)
    assert [u.kind for u in fresh] == [UnitKind.OUTLINE] and fresh[0].new_outline
    assert container.tutorial_service.plan_part_units(subject, parts=[0]) == [
        u for u in units[1:] if u.part_position == 0
    ]


def test_run_unit_for_a_part_replaces_its_content_without_a_new_version(container):
    subject = _ingested_subject(container)
    container.tutorial_service.generate(subject)
    outline = container.outlines.latest(subject.id)
    part = next(p for p in container.outlines.parts(outline.id) if p.position == 0)
    questions_before = len(container.questions.for_part(part.id, "he"))
    sections_before = len(container.content.sections(part.id, "he"))

    unit = GenerationUnit(
        kind=UnitKind.PART,
        subject_id=subject.id,
        outline_version=outline.version,
        part_position=0,
        language="he",
    )
    result = container.tutorial_service.run_unit(unit).part
    assert result is not None
    assert result.content_status is ContentStatus.READY and result.part_position == 0

    content = container.content.part(part.id, "he")
    assert content is not None and content.status is ContentStatus.READY
    assert len(container.questions.for_part(part.id, "he")) == questions_before
    assert len(container.content.sections(part.id, "he")) == sections_before
    assert container.outlines.latest(subject.id).version == outline.version
    assert container.tutorial_service.status(subject).publishable


def test_generate_subject_job_runs_the_outline_then_one_job_per_unit(container):
    subject = _ingested_subject(container)
    container.job_runner.enqueue(
        GENERATE_SUBJECT, GenerateSubjectJob(subject_id=subject.id).model_dump(mode="json")
    )
    assert container.tutorial_service.status(subject).publishable

    outline = container.outlines.latest(subject.id)
    expected_units = len(container.outlines.parts(outline.id)) * 2
    rows = container.conn.execute("SELECT kind, status, payload FROM jobs ORDER BY created_at").fetchall()
    assert [r["kind"] for r in rows] == [GENERATE_SUBJECT] + [GENERATE_UNIT] * expected_units
    assert all(r["status"] == "done" for r in rows)
    units = [GenerateUnitJob.model_validate(r["payload"]).unit for r in rows[1:]]
    assert all(u.outline_version == outline.version for u in units)
    assert {(u.language, u.part_position) for u in units} == {
        (language, part.position)
        for language in ("he", "en")
        for part in container.outlines.parts(outline.id)
    }


def test_a_failing_unit_is_recorded_on_its_own_job_and_leaves_the_others_alone(container):
    subject = _ingested_subject(container, pages=9)
    teaching = default_responders()[TeachingOut]
    calls = {"n": 0}

    def fail_the_first_part(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("teaching service down")
        return teaching(request)

    container.llm.inner.set_responder(TeachingOut, fail_the_first_part)
    container.job_runner.enqueue(
        GENERATE_SUBJECT,
        GenerateSubjectJob(subject_id=subject.id, languages=("he",)).model_dump(mode="json"),
    )

    rows = container.conn.execute(
        "SELECT status, error, payload FROM jobs WHERE kind = %s ORDER BY created_at", (GENERATE_UNIT,)
    ).fetchall()
    failed = [r for r in rows if r["status"] == "failed"]
    assert len(failed) == 1 and "teaching service down" in failed[0]["error"]
    assert all(r["status"] == "done" for r in rows if r is not failed[0])
    # the subject-level job still succeeded: its own work (the outline) was done, and the parts
    # it fanned out answer for themselves
    subject_job = container.conn.execute(
        "SELECT status FROM jobs WHERE kind = %s", (GENERATE_SUBJECT,)
    ).fetchone()
    assert subject_job["status"] == "done"

    outline = container.outlines.latest(subject.id)
    parts = container.outlines.parts(outline.id)
    broken = GenerateUnitJob.model_validate(failed[0]["payload"]).unit
    for part in parts:
        content = container.content.part(part.id, "he")
        assert content is not None
        expected = ContentStatus.FAILED if part.position == broken.part_position else ContentStatus.READY
        assert content.status is expected


def test_interleaved_runs_pin_their_part_units_to_the_version_they_created(container):
    """Two runs of the same subject, on two connections, overlapping. The second one creates a
    newer outline version before the first has planned its parts: what pins the first run's parts
    is the version its own outline unit produced, not whatever `latest()` says by then."""
    subject = _ingested_subject(container, languages=("he",))
    other = Container(container.settings)
    try:
        first, second = container.tutorial_service, other.tutorial_service
        mine = first.run_unit(first.plan_generation(subject)[0]).outline
        theirs = second.run_unit(second.plan_generation(subject)[0]).outline
        assert (mine.version, theirs.version) == (1, 2)

        my_units = first.plan_part_units(subject, outline_version=mine.version)
        their_units = second.plan_part_units(subject, outline_version=theirs.version)
        assert my_units and {u.outline_version for u in my_units} == {1}
        assert their_units and {u.outline_version for u in their_units} == {2}
    finally:
        other.close()


def test_a_generate_unit_job_refuses_an_outline_unit():
    """The outline unit is the one unit that may create a version; it belongs to the subject-level
    handler, which resolves that decision once. A job that carried it would create a second."""
    with pytest.raises(ValidationError, match="PART"):
        GenerateUnitJob(unit=GenerationUnit(kind=UnitKind.OUTLINE, subject_id=uuid4()))


def test_a_redelivered_generate_subject_job_reuses_the_version_it_created(container):
    """At-least-once delivery: the same message arrives twice. The first run's decision to create
    a version is recorded on the job row, so the second delivery reuses it instead of creating a
    second version, and re-enqueues only the part units that are not already done."""
    subject = _ingested_subject(container, languages=("he",))
    payload = GenerateSubjectJob(subject_id=subject.id).model_dump(mode="json")
    job_id = container.jobs.create(GENERATE_SUBJECT, payload)
    container.conn.commit()

    handler = container.job_handlers[GENERATE_SUBJECT]
    handler(payload, job_id)
    handler(payload, job_id)

    assert [o.version for o in container.outlines.versions(subject.id)] == [1]
    assert container.jobs.get(job_id)["result"] == {"outline_version": 1}

    rows = container.conn.execute("SELECT payload FROM jobs WHERE kind = %s", (GENERATE_UNIT,)).fetchall()
    units = [GenerateUnitJob.model_validate(r["payload"]).unit for r in rows]
    assert units and all(u.outline_version == 1 for u in units)
    assert len(units) == len({(u.part_position, u.language) for u in units})
    assert container.tutorial_service.status(subject).publishable
