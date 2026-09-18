from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from enum import StrEnum
from uuid import UUID, uuid4

import psycopg
from pydantic import BaseModel, ConfigDict

from teachme.domain.glossary.render import GlossaryView, render_placeholders
from teachme.domain.models import (
    ContentStatus,
    GlossaryTerm,
    GlossaryTranslation,
    Outline,
    Part,
    PartContent,
    Question,
    Section,
    SectionContent,
    Source,
    SourceStatus,
    Subject,
    SubjectState,
)
from teachme.generation.bundle import SubjectBundleWriter
from teachme.generation.corpus import SubjectCorpus, build_corpus, dominant_language
from teachme.generation.errors import GenerationError, SubjectNotReady
from teachme.generation.glossary import generate_glossary, translate_glossary
from teachme.generation.outline import generate_outline
from teachme.generation.question_bank import generate_question_bank, to_questions
from teachme.generation.teaching import TeachingOut, generate_teaching
from teachme.ingestion.bundle import bundle_slug
from teachme.ingestion.errors import SubjectLocked
from teachme.ports.file_store import FileStore
from teachme.ports.llm import LLMError, LLMProvider
from teachme.repositories.content import ContentRepository
from teachme.repositories.glossary import GlossaryRepository
from teachme.repositories.outlines import OutlineRepository
from teachme.repositories.pages import PageRepository
from teachme.repositories.questions import QuestionRepository
from teachme.repositories.sources import SourceRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.settings import Settings
from teachme.telemetry.usage import usage_context

log = logging.getLogger(__name__)

MIN_QUESTIONS_PER_SECTION = 2
VersionListener = Callable[[Subject, int], None]


class PartLanguageResult(BaseModel):
    part_position: int
    language: str
    content_status: ContentStatus
    questions: int
    error: str | None = None


class UnitResult(BaseModel):
    """What running one unit produced. An OUTLINE unit answers with the outline version it created
    or reused, which is what the caller pins that run's part units to; a PART unit answers with its
    own per-language result. Exactly one of the two is set, by the unit's kind."""

    model_config = ConfigDict(frozen=True)

    outline: Outline | None = None
    part: PartLanguageResult | None = None


class GenerationReport(BaseModel):
    subject: str
    outline_version: int
    new_outline: bool
    results: list[PartLanguageResult]

    @property
    def failures(self) -> list[PartLanguageResult]:
        return [r for r in self.results if r.content_status != ContentStatus.READY]


class UnitKind(StrEnum):
    OUTLINE = "outline"
    PART = "part"


class GenerationUnit(BaseModel):
    """One job-sized piece of a generation run. It travels in a job payload, so every field is a
    plain serializable value and nothing is carried in memory between units.

    OUTLINE: the subject's outline and glossary, plus the glossary translations of `languages`.
    PART: the teaching text and question bank of one part, in one language, against one outline
    version.

    Idempotence. A PART unit replaces the part's content, its section content and its questions for
    its language, so running it twice leaves exactly one copy of each and a retry is free, and it
    names the version it belongs to rather than asking for the newest one, so a version created in
    between cannot steal it. An OUTLINE unit with new_outline=False reuses the current version - it
    creates one only when the subject has none at all - and rewrites the glossary translations in
    place, so it is idempotent too. new_outline=True is the one unit that is not, by definition: it
    is an explicit request for a fresh version, which is what a full `teachme generate` means.

    The guarantee, precisely: one `generate_subject` job creates at most one outline version,
    however many times its message is delivered. Only that handler ever runs an OUTLINE unit -
    GenerateUnitJob refuses to carry one - and it resolves new_outline exactly once, recording the
    version it produced on its own job row before enqueuing anything. A redelivery reads that back,
    runs no outline unit, and re-enqueues only the part units whose own job has not already
    finished. Every part unit it enqueues is pinned to that version, so no retry, at any level,
    can produce a second one."""

    model_config = ConfigDict(frozen=True)

    kind: UnitKind
    subject_id: UUID
    languages: tuple[str, ...] = ()  # OUTLINE: the languages whose glossary translations it owns
    new_outline: bool = False  # OUTLINE: create a version rather than reuse the current one
    # PART: the version it belongs to. OUTLINE: the version to reuse, when new_outline is False -
    # a plan that already named its parts against a version must run its outline unit against that
    # same one, or the two halves of the plan would answer to different versions.
    outline_version: int | None = None
    part_position: int | None = None  # PART
    language: str | None = None  # PART


class LanguageStatus(BaseModel):
    language: str
    parts_ready: int
    parts_total: int
    questions: int
    complete: bool
    failed: tuple[int, ...] = ()


class TutorialStatus(BaseModel):
    subject: str
    state: SubjectState
    outline_version: int | None
    published_version: int | None
    parts: int
    languages: list[LanguageStatus]
    publishable: bool
    publishable_version: int | None = None


class GlossaryEntry(BaseModel):
    slug: str
    term: str
    source_term: str
    definition: str


class RenderedPart(BaseModel):
    outline_version: int
    published: bool
    position: int
    title: str
    body: str
    key_points: tuple[str, ...]
    # Global corpus page indices the body points at, for GET /api/subjects/{id}/pages/{i}/image.
    page_refs: tuple[int, ...]
    # What the book prints on each of those pages, parallel to page_refs - "" for a page that
    # carries no printed number. A corpus index is an internal address; this is what a reader
    # sees on the page, and the only page number worth showing them.
    page_labels: tuple[str, ...]
    sections: list[SectionContent]
    glossary: list[GlossaryEntry]


class TutorialService:
    """Generates, versions, publishes and renders a subject's tutorial. The model is called only
    through the generation modules; this class owns ordering, persistence, bundle writes and commits."""

    def __init__(
        self,
        conn: psycopg.Connection,
        settings: Settings,
        llm: LLMProvider,
        subjects: SubjectRepository,
        sources: SourceRepository,
        pages: PageRepository,
        outlines: OutlineRepository,
        glossary: GlossaryRepository,
        content: ContentRepository,
        questions: QuestionRepository,
        bundle_stores: Sequence[FileStore],
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._llm = llm
        self._subjects = subjects
        self._sources = sources
        self._pages = pages
        self._outlines = outlines
        self._glossary = glossary
        self._content = content
        self._questions = questions
        self._bundle_stores = bundle_stores
        self._listeners: list[VersionListener] = []

    # generation -----------------------------------------------------------------------------
    def _require_ready_sources(self, subject: Subject) -> list[Source]:
        """The subject's sources, or the reason there is nothing to generate from. Cheap enough to
        ask before planning a run, which is where a refusal still reaches whoever asked for it."""
        sources = self._sources.list_by_subject(subject.id)
        if not sources:
            raise SubjectNotReady(f"subject {subject.name!r} has no sources")
        not_ready = [s.filename for s in sources if s.status != SourceStatus.READY]
        if not_ready:
            raise SubjectNotReady(f"sources not ready: {not_ready}")
        return sources

    def corpus(self, subject: Subject) -> SubjectCorpus:
        sources = self._require_ready_sources(subject)
        return build_corpus(sources, {s.id: self._pages.list(s.id) for s in sources})

    def generate(
        self,
        subject: Subject,
        *,
        languages: Sequence[str] | None = None,
        parts: Sequence[int] | None = None,
        content_only: bool = False,
    ) -> GenerationReport:
        """Every unit of one run, in order, in this process - what the CLI calls. The parts are
        planned after the outline unit has run, because a run that creates a new version only
        learns its parts by creating them."""
        plan = self.plan_generation(subject, languages=languages, parts=parts, content_only=content_only)
        outline_unit = plan[0]
        outline = self.run_unit(outline_unit).outline
        assert outline is not None  # the outline unit created or reused one, or it raised
        # A run that reused the current version was planned in full: those units are the answer.
        # Only a run that created a version has parts the plan could not name yet.
        part_units = (
            self.plan_part_units(subject, languages=languages, parts=parts, outline_version=outline.version)
            if outline_unit.new_outline
            else plan[1:]
        )
        results = [result for unit in part_units if (result := self.run_unit(unit).part) is not None]
        return GenerationReport(
            subject=subject.name,
            outline_version=outline.version,
            new_outline=outline_unit.new_outline,
            results=results,
        )

    def plan_generation(
        self,
        subject: Subject,
        *,
        languages: Sequence[str] | None = None,
        parts: Sequence[int] | None = None,
        content_only: bool = False,
    ) -> list[GenerationUnit]:
        """The units of one run, in order: the outline and glossary unit first, then one unit per
        part and language (language-major, the order the report lists results in).

        The parts of an outline version that does not exist yet cannot be named, so a run that will
        create one stops after the outline unit; running that unit makes the parts real and
        `plan_part_units` then returns them. Everything a run can refuse - a published subject, a
        subject whose sources are not ready, a language the subject does not have, a part position
        the current outline does not have - is refused here, before the first model call, so that a
        caller enqueuing this plan hears it instead of a job nobody is watching."""
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before generating")
        self._require_ready_sources(subject)  # the same check the run makes, made while asked
        chosen_languages = self._chosen_languages(subject, languages)
        outline = self._outlines.latest(subject.id)
        # A content-only run, and any run that names parts, reuses the current version:
        # regenerating one part into a fresh outline would leave the other parts empty.
        new_outline = outline is None or (not content_only and parts is None)
        self._wanted_parts(outline, parts)  # validate against the current outline, before any call
        unit = GenerationUnit(
            kind=UnitKind.OUTLINE,
            subject_id=subject.id,
            languages=tuple(chosen_languages),
            new_outline=new_outline,
            outline_version=None if new_outline or outline is None else outline.version,
        )
        if new_outline or outline is None:
            return [unit]
        return [
            unit,
            *self.plan_part_units(subject, languages=languages, parts=parts, outline_version=outline.version),
        ]

    def plan_part_units(
        self,
        subject: Subject,
        *,
        languages: Sequence[str] | None = None,
        parts: Sequence[int] | None = None,
        outline_version: int | None = None,
    ) -> list[GenerationUnit]:
        """One unit per part and language against one outline version. Called after an outline unit
        has run, which is when a new version's parts become known - so the caller passes the
        version that unit answered with. Falling back to the newest version is only safe when no
        outline unit ran: another run that created a version in between would otherwise steal these
        parts, pinning them to an outline this run never produced."""
        chosen_languages = self._chosen_languages(subject, languages)
        outline = (
            self._outlines.latest(subject.id)
            if outline_version is None
            else self._outlines.get_version(subject.id, outline_version)
        )
        wanted = self._wanted_parts(outline, parts)
        if outline is None:
            return []
        return [
            GenerationUnit(
                kind=UnitKind.PART,
                subject_id=subject.id,
                outline_version=outline.version,
                part_position=part.position,
                language=language,
            )
            for language in chosen_languages
            for part in wanted
        ]

    def run_unit(self, unit: GenerationUnit) -> UnitResult:
        """Runs one unit to completion and commits it, answering with what it produced: the outline
        version for an OUTLINE unit, the part's result for a PART one. A part the model could not
        produce comes back as a FAILED result rather than an exception, exactly as it does inside a
        whole run; anything else rolls the transaction back and propagates, so nothing half-written
        - an outline version without its glossary, above all - survives for a later commit to keep."""
        subject = self._subjects.get(unit.subject_id)
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before generating")
        try:
            with usage_context(subject_id=subject.id):
                if unit.kind is UnitKind.OUTLINE:
                    return UnitResult(outline=self._run_outline_unit(subject, unit))
                return UnitResult(part=self._run_part_unit(subject, unit))
        except Exception:
            self._conn.rollback()
            raise

    def _chosen_languages(self, subject: Subject, languages: Sequence[str] | None) -> list[str]:
        chosen = list(languages or subject.languages)
        unknown = [code for code in chosen if code not in subject.languages]
        if unknown:
            raise GenerationError(f"languages not enabled for this subject: {unknown}")
        return chosen

    def _wanted_parts(self, outline: Outline | None, parts: Sequence[int] | None) -> list[Part]:
        all_parts = [] if outline is None else self._outlines.parts(outline.id)
        if parts is None:
            return all_parts
        unknown = sorted(set(parts) - {p.position for p in all_parts})
        if unknown:
            raise GenerationError(f"no such parts: {unknown}")
        return [p for p in all_parts if p.position in parts]

    def _run_outline_unit(self, subject: Subject, unit: GenerationUnit) -> Outline:
        corpus = self.corpus(subject)
        slug = bundle_slug(subject.name, subject.id)
        model = self._settings.model_generation
        outline = (
            self._outlines.latest(subject.id)
            if unit.outline_version is None
            else self._outlines.get_version(subject.id, unit.outline_version)
        )
        if unit.outline_version is not None and outline is None:
            raise GenerationError(f"subject {subject.name!r} has no outline v{unit.outline_version}")
        if unit.new_outline or outline is None:
            outline = self._create_outline(subject, corpus, model, slug)
        writer = SubjectBundleWriter(self._bundle_stores, slug, outline.version)
        terms = self._glossary.terms(outline.id)
        for language in unit.languages:
            self._ensure_translations(outline, corpus, language, terms, model, writer)
        return outline

    def _run_part_unit(self, subject: Subject, unit: GenerationUnit) -> PartLanguageResult:
        assert unit.language is not None and unit.part_position is not None
        outline = (
            self._outlines.latest(subject.id)
            if unit.outline_version is None
            else self._outlines.get_version(subject.id, unit.outline_version)
        )
        if outline is None:
            raise GenerationError(f"subject {subject.name!r} has no outline v{unit.outline_version}")
        latest = self._outlines.latest(subject.id)
        if latest is not None and latest.version != outline.version:
            # Legitimate for a run that started before someone else created a version, and exactly
            # what a part unit that lost its pin would look like - so it is never silent.
            log.warning(
                "part %s [%s] of %r is being generated against outline v%s, which is no longer "
                "the latest (v%s)",
                unit.part_position,
                unit.language,
                subject.name,
                outline.version,
                latest.version,
            )
        part = next((p for p in self._outlines.parts(outline.id) if p.position == unit.part_position), None)
        if part is None:
            raise GenerationError(f"no such parts: [{unit.part_position}]")
        corpus = self.corpus(subject)
        model = self._settings.model_generation
        writer = SubjectBundleWriter(
            self._bundle_stores, bundle_slug(subject.name, subject.id), outline.version
        )
        terms = self._glossary.terms(outline.id)
        # Cheap when the outline unit already wrote them: a complete set is read, not regenerated.
        translations = self._ensure_translations(outline, corpus, unit.language, terms, model, writer)
        return self._generate_part(
            subject, corpus, outline, part, unit.language, terms, translations, model, writer
        )

    def _create_outline(self, subject: Subject, corpus: SubjectCorpus, model: str, slug: str) -> Outline:
        outline_out = generate_outline(self._llm, model, subject.name, corpus)
        outline = self._outlines.create(subject.id, model=model)
        writer = SubjectBundleWriter(self._bundle_stores, slug, outline.version)
        structure: list[tuple[Part, list[Section]]] = []
        for position, part_out in enumerate(outline_out.parts):
            part = self._outlines.add_part(
                outline.id,
                position=position,
                title=part_out.title,
                page_start=part_out.page_start,
                page_end=part_out.page_end,
            )
            sections = [
                self._outlines.add_section(
                    part.id, position=i, title=s.title, page_start=s.page_start, page_end=s.page_end
                )
                for i, s in enumerate(part_out.sections)
            ]
            structure.append((part, sections))
        glossary_out = generate_glossary(self._llm, model, subject.name, corpus)
        terms = [
            GlossaryTerm(
                id=uuid4(),
                outline_id=outline.id,
                slug=t.slug,
                source_term=t.term,
                definition=t.definition,
                pages=tuple(t.pages),
            )
            for t in glossary_out.terms
        ]
        self._glossary.replace_terms(outline.id, terms)
        writer.write_outline(outline, structure)
        writer.write_glossary(terms)
        self._conn.commit()
        return outline

    def _ensure_translations(
        self,
        outline: Outline,
        corpus: SubjectCorpus,
        language: str,
        terms: Sequence[GlossaryTerm],
        model: str,
        writer: SubjectBundleWriter,
    ) -> dict[str, str]:
        existing = {t.term_id: t.term for t in self._glossary.translations(outline.id, language)}
        if not terms:
            return {}
        if len(existing) == len(terms) and all(t.id in existing for t in terms):
            return {t.slug: existing[t.id] for t in terms}
        if corpus.language == language:
            mapping = {t.slug: t.source_term for t in terms}
        else:
            out = translate_glossary(self._llm, model, language, terms)
            mapping = {tr.slug: tr.term for tr in out.translations}
        by_slug = {t.slug: t.id for t in terms}
        self._glossary.replace_translations(
            outline.id,
            language,
            [
                GlossaryTranslation(term_id=by_slug[slug], language=language, term=term)
                for slug, term in mapping.items()
            ],
        )
        writer.write_translations(language, mapping)
        self._conn.commit()
        return mapping

    def _generate_part(
        self,
        subject: Subject,
        corpus: SubjectCorpus,
        outline: Outline,
        part: Part,
        language: str,
        terms: Sequence[GlossaryTerm],
        translations: dict[str, str],
        model: str,
        writer: SubjectBundleWriter,
    ) -> PartLanguageResult:
        sections = self._outlines.sections(part.id)
        try:
            teaching = generate_teaching(
                self._llm, model, subject.name, language, corpus, part, sections, terms, translations
            )
            content = PartContent(
                part_id=part.id,
                language=language,
                title=teaching.title,
                body=teaching.body_markdown,
                key_points=tuple(teaching.key_points),
                status=ContentStatus.READY,
                model=model,
                page_refs=tuple(teaching.page_refs),
            )
            self._content.upsert_part(content)
            by_position = {s.position: s.id for s in sections}
            self._content.upsert_sections(
                [
                    SectionContent(
                        section_id=by_position[sc.position],
                        language=language,
                        title=sc.title,
                        summary=sc.summary,
                    )
                    for sc in teaching.sections
                ]
            )
            questions = self._generate_questions(
                subject,
                corpus,
                outline,
                part,
                sections,
                language,
                teaching,
                terms,
                translations,
                model,
                writer,
            )
            writer.write_part_content(part, content)  # bundle files only once the part succeeded
            self._conn.commit()
            return PartLanguageResult(
                part_position=part.position,
                language=language,
                content_status=ContentStatus.READY,
                questions=len(questions),
            )
        except (GenerationError, LLMError, ValueError) as exc:
            # The rollback discards this attempt's uncommitted writes, but a *previous* successful
            # attempt's rows (section content, questions) may still be sitting there committed from
            # an earlier generate() call - a FAILED part must not keep half of a stale good attempt,
            # so those are explicitly cleared here rather than assumed gone.
            self._conn.rollback()
            self._content.delete_sections(part.id, language)
            self._questions.replace_for_part(part.id, language, [])
            failed = PartContent(
                part_id=part.id,
                language=language,
                title=part.title,
                body="",
                key_points=(),
                status=ContentStatus.FAILED,
                model=model,
                error=str(exc),
            )
            self._content.upsert_part(failed)
            writer.write_part_content(part, failed)
            self._write_questions_bundle(outline, language, writer)
            self._conn.commit()
            return PartLanguageResult(
                part_position=part.position,
                language=language,
                content_status=ContentStatus.FAILED,
                questions=0,
                error=str(exc),
            )

    def _generate_questions(
        self,
        subject: Subject,
        corpus: SubjectCorpus,
        outline: Outline,
        part: Part,
        sections: Sequence[Section],
        language: str,
        teaching: TeachingOut,
        terms: Sequence[GlossaryTerm],
        translations: dict[str, str],
        model: str,
        writer: SubjectBundleWriter,
    ) -> list[Question]:
        bank = generate_question_bank(
            self._llm,
            model,
            subject.name,
            language,
            corpus,
            part,
            sections,
            teaching,
            terms,
            translations,
            count=subject.bank_size_per_part,
            min_per_section=MIN_QUESTIONS_PER_SECTION,
        )
        source_terms = {t.slug: t.source_term for t in terms}
        questions = to_questions(bank, sections, language, source_terms, translations)
        self._questions.replace_for_part(part.id, language, questions)
        self._write_questions_bundle(outline, language, writer)
        return questions

    def _write_questions_bundle(self, outline: Outline, language: str, writer: SubjectBundleWriter) -> None:
        """Rebuilds questions.<lang>.jsonl for the whole outline from the DB, so it always
        reflects the current state of every part - including one just cleared after a failure."""
        positions: dict[UUID, tuple[int, int]] = {}
        all_for_language: list[Question] = []
        for other in self._outlines.parts(outline.id):
            other_sections = self._outlines.sections(other.id)
            positions.update({s.id: (other.position, s.position) for s in other_sections})
            all_for_language.extend(self._questions.for_part(other.id, language))
        writer.write_questions(language, all_for_language, positions)

    # status and publishing ------------------------------------------------------------------
    def _evaluate(self, subject: Subject, outline: Outline) -> TutorialStatus:
        """Per-language readiness of one outline version. publishable_version is left unset here:
        it depends on every version, not just this one - callers that need it fill it in."""
        parts = self._outlines.parts(outline.id)
        ready = self._content.languages_ready(outline.id)
        failed = self._content.languages_failed(outline.id)
        languages: list[LanguageStatus] = []
        for language in subject.languages:
            counts = [self._questions.count_by_section(p.id, language) for p in parts]
            total_questions = sum(sum(c.values()) for c in counts)
            enough = all(
                all(c.get(s.id, 0) >= MIN_QUESTIONS_PER_SECTION for s in self._outlines.sections(p.id))
                for p, c in zip(parts, counts, strict=True)
            )
            parts_ready = ready.get(language, 0)
            languages.append(
                LanguageStatus(
                    language=language,
                    parts_ready=parts_ready,
                    parts_total=len(parts),
                    questions=total_questions,
                    complete=parts_ready == len(parts) and enough,
                    failed=failed.get(language, ()),
                )
            )
        return TutorialStatus(
            subject=subject.name,
            state=subject.state,
            outline_version=outline.version,
            published_version=subject.current_outline_version,
            parts=len(parts),
            languages=languages,
            publishable=bool(parts) and all(lang.complete for lang in languages),
        )

    def _find_publishable(self, subject: Subject) -> tuple[TutorialStatus | None, TutorialStatus | None]:
        """Walk outline versions newest-first, exactly as `publish` would: the first complete one
        wins. Returns (the newest version's evaluation, the first publishable one), either of
        which may be None when the subject has no outline at all or nothing is publishable."""
        latest: TutorialStatus | None = None
        found: TutorialStatus | None = None
        for outline in self._outlines.versions(subject.id):
            candidate = self._evaluate(subject, outline)
            latest = latest or candidate
            if candidate.publishable:
                found = candidate
                break
        return latest, found

    def status(self, subject: Subject, outline: Outline | None = None) -> TutorialStatus:
        """Readiness of one outline version; the latest one unless a version is given.
        publishable_version names the version `publish` would actually select, which may be an
        older one than the version detailed here."""
        if outline is None:
            outline = self._outlines.latest(subject.id)
        if outline is None:
            return TutorialStatus(
                subject=subject.name,
                state=subject.state,
                outline_version=None,
                published_version=subject.current_outline_version,
                parts=0,
                languages=[],
                publishable=False,
                publishable_version=None,
            )
        target = self._evaluate(subject, outline)
        _, found = self._find_publishable(subject)
        return target.model_copy(update={"publishable_version": found.outline_version if found else None})

    def on_version_published(self, listener: VersionListener) -> None:
        """Stage 3 registers the progress reset here; called only when the published version changes."""
        self._listeners.append(listener)

    def publish(self, subject: Subject) -> Subject:
        """Publish the newest complete version. A draft regeneration that is still incomplete (or
        failed) therefore never blocks publishing, and never unpublishes what students are using."""
        latest, status = self._find_publishable(subject)
        if status is None:
            incomplete = (
                [lang.language for lang in latest.languages if not lang.complete] if latest else []
            ) or ["no outline"]
            raise SubjectNotReady(f"cannot publish {subject.name!r}: incomplete for {incomplete}")
        assert status.outline_version is not None
        changed = subject.current_outline_version != status.outline_version
        self._subjects.set_current_outline_version(subject.id, status.outline_version)
        self._subjects.set_state(subject.id, SubjectState.PUBLISHED)
        self._conn.commit()
        published = self._subjects.get(subject.id)
        if changed:
            for listener in self._listeners:
                listener(published, status.outline_version)
        return published

    def unpublish(self, subject: Subject) -> Subject:
        self._subjects.set_state(subject.id, SubjectState.DRAFT)
        self._conn.commit()
        return self._subjects.get(subject.id)

    # rendering ------------------------------------------------------------------------------
    def rendered_part(
        self, subject: Subject, language: str, part_position: int, *, draft: bool = False
    ) -> RenderedPart:
        """The published version of a part, or with draft=True the latest version of it."""
        version = subject.current_outline_version
        outline = (
            self._outlines.latest(subject.id)
            if draft or version is None
            else self._outlines.get_version(subject.id, version)
        )
        if outline is None:
            raise SubjectNotReady(f"subject {subject.name!r} has no outline")
        part = next((p for p in self._outlines.parts(outline.id) if p.position == part_position), None)
        if part is None:
            raise SubjectNotReady(f"no part {part_position} in outline version {outline.version}")
        content = self._content.part(part.id, language)
        if content is None or content.status != ContentStatus.READY:
            raise SubjectNotReady(f"part {part_position} has no ready content in {language!r}")
        terms = self._glossary.terms(outline.id)
        translations = {t.term_id: t.term for t in self._glossary.translations(outline.id, language)}
        sources = self._sources.list_by_subject(subject.id)
        view = GlossaryView(
            source_language=dominant_language(sources),
            source_terms={t.slug: t.source_term for t in terms},
        )
        body = render_placeholders(
            content.body, view, target_language=language, frequency=subject.gloss_frequency
        )
        return RenderedPart(
            outline_version=outline.version,
            published=(
                subject.state == SubjectState.PUBLISHED and outline.version == subject.current_outline_version
            ),
            position=part.position,
            title=content.title,
            body=body,
            key_points=content.key_points,
            page_refs=content.page_refs,
            page_labels=self._page_labels(sources, content.page_refs),
            sections=self._content.sections(part.id, language),
            glossary=[
                GlossaryEntry(
                    slug=t.slug,
                    term=translations.get(t.id, t.source_term),
                    source_term=t.source_term,
                    definition=t.definition,
                )
                for t in terms
            ],
        )

    def _page_labels(self, sources: Sequence[Source], page_refs: Sequence[int]) -> tuple[str, ...]:
        """The printed number of each referenced page, or "" where the page carries none. The
        indices are global corpus indices, so the ready sources' pages are laid end to end in
        source order - the same order build_corpus numbers them in."""
        ready = [s for s in sources if s.status == SourceStatus.READY]
        by_source = self._pages.printed_numbers([s.id for s in ready])
        printed = [number for source in ready for number in by_source.get(source.id, ())]
        return tuple(printed[index] if 0 <= index < len(printed) else "" for index in page_refs)
