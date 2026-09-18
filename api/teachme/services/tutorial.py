from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import UUID, uuid4

import psycopg
from pydantic import BaseModel

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

MIN_QUESTIONS_PER_SECTION = 2
VersionListener = Callable[[Subject, int], None]


class PartLanguageResult(BaseModel):
    part_position: int
    language: str
    content_status: ContentStatus
    questions: int
    error: str | None = None


class GenerationReport(BaseModel):
    subject: str
    outline_version: int
    new_outline: bool
    results: list[PartLanguageResult]

    @property
    def failures(self) -> list[PartLanguageResult]:
        return [r for r in self.results if r.content_status != ContentStatus.READY]


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
    def corpus(self, subject: Subject) -> SubjectCorpus:
        sources = self._sources.list_by_subject(subject.id)
        if not sources:
            raise SubjectNotReady(f"subject {subject.name!r} has no sources")
        not_ready = [s.filename for s in sources if s.status != SourceStatus.READY]
        if not_ready:
            raise SubjectNotReady(f"sources not ready: {not_ready}")
        return build_corpus(sources, {s.id: self._pages.list(s.id) for s in sources})

    def generate(
        self,
        subject: Subject,
        *,
        languages: Sequence[str] | None = None,
        parts: Sequence[int] | None = None,
        content_only: bool = False,
    ) -> GenerationReport:
        if subject.state == SubjectState.PUBLISHED:
            raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before generating")
        chosen_languages = list(languages or subject.languages)
        unknown = [code for code in chosen_languages if code not in subject.languages]
        if unknown:
            raise GenerationError(f"languages not enabled for this subject: {unknown}")
        corpus = self.corpus(subject)
        slug = bundle_slug(subject.name, subject.id)
        model = self._settings.model_generation

        try:
            with usage_context(subject_id=subject.id):
                outline = self._outlines.latest(subject.id)
                # A content-only run, and any run that names parts, reuses the current version:
                # regenerating one part into a fresh outline would leave the other parts empty.
                new_outline = outline is None or (not content_only and parts is None)
                all_parts = [] if outline is None else self._outlines.parts(outline.id)
                if parts is not None:  # validate against the current outline, before any model call
                    unknown = sorted(set(parts) - {p.position for p in all_parts})
                    if unknown:
                        raise GenerationError(f"no such parts: {unknown}")
                if new_outline:
                    outline = self._create_outline(subject, corpus, model, slug)
                    all_parts = self._outlines.parts(outline.id)
                assert outline is not None
                writer = SubjectBundleWriter(self._bundle_stores, slug, outline.version)
                terms = self._glossary.terms(outline.id)
                wanted = [p for p in all_parts if parts is None or p.position in parts]

                results: list[PartLanguageResult] = []
                for language in chosen_languages:
                    translations = self._ensure_translations(outline, corpus, language, terms, model, writer)
                    for part in wanted:
                        results.append(
                            self._generate_part(
                                subject, corpus, outline, part, language, terms, translations, model, writer
                            )
                        )
        except Exception:
            # Nothing half-written survives: the outline version, its parts and its glossary are
            # all created in one uncommitted transaction, so a failure before the commit in
            # _create_outline must not leave a dangling version behind for a later commit to keep.
            self._conn.rollback()
            raise
        return GenerationReport(
            subject=subject.name,
            outline_version=outline.version,
            new_outline=new_outline,
            results=results,
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
