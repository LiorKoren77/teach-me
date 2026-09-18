from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import typer

from teachme.adapters.db.migrate import SchemaOutOfDate, apply_migrations, ensure_schema_current
from teachme.container import ConfigurationError, Container
from teachme.domain.models import Source
from teachme.generation.errors import GenerationError
from teachme.ingestion.errors import ExtractionError, IngestionError, SubjectLocked, UnsupportedMediaType
from teachme.ingestion.estimate import estimate_ingest
from teachme.ingestion.pdf_pages import page_count
from teachme.ports.file_store import FileNotFound
from teachme.repositories.errors import NotFound
from teachme.services.subjects import LanguageNotEnabled

app = typer.Typer(no_args_is_help=True, help="teach-me operator commands")
subject_app = typer.Typer(no_args_is_help=True, help="Manage subjects")
source_app = typer.Typer(no_args_is_help=True, help="Manage sources")
tutorial_app = typer.Typer(no_args_is_help=True, help="Inspect the generated tutorial")
app.add_typer(subject_app, name="subject")
app.add_typer(source_app, name="source")
app.add_typer(tutorial_app, name="tutorial")

_OPERATOR_ERRORS = (
    NotFound,
    SubjectLocked,
    UnsupportedMediaType,
    LanguageNotEnabled,
    IngestionError,
    FileNotFound,
    ConfigurationError,
    GenerationError,
)


def build_container(check_schema: bool = True) -> Container:
    """Patched in tests. One Container per command invocation.

    check_schema=True (the default) fails fast with a plain message when the database schema is
    behind, instead of letting every command hit its own confusing error partway through.
    `migrate` is the one command that must run against an out-of-date schema, so it opts out.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    c = Container()
    if check_schema:
        try:
            ensure_schema_current(c.conn)
        except SchemaOutOfDate as exc:
            typer.echo(str(exc), err=True)
            c.close()
            raise typer.Exit(1) from exc
    return c


def _run(body: Callable[[Container], None], *, check_schema: bool = True) -> None:
    """Builds the container, runs body(container), and always closes it. Operator-facing errors
    (a missing subject, a locked subject, a rejected upload, a misconfigured adapter, ...) are
    reported as a plain `error: ...` line on stderr with exit code 1 instead of a traceback;
    anything else propagates so it shows up as the bug it is."""
    c = build_container(check_schema=check_schema)
    try:
        body(c)
    except _OPERATOR_ERRORS as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        c.close()


def _estimated_pages(path: Path) -> int:
    """Best-effort page count for the up-front cost estimate. A file that turns out to be
    unreadable is estimated as 1 page; the per-file loop in `ingest` reports the real failure."""
    if path.suffix.lower() != ".pdf":
        return 1
    try:
        return page_count(path.read_bytes())
    except ExtractionError:
        return 1


def _describe(source: Source) -> str:
    pages = f"{source.page_count} pages" if source.page_count is not None else "pages unknown"
    detail = f", language {source.detected_language}" if source.detected_language else ""
    error = f" error: {source.error}" if source.error else ""
    return f"{source.filename}: {source.status.value} ({pages}{detail}){error}"


@app.command()
def migrate() -> None:
    """Apply pending database migrations."""

    def body(c: Container) -> None:
        applied = apply_migrations(c.conn)
        typer.echo(f"applied: {applied}" if applied else "schema already current")

    _run(body, check_schema=False)


@subject_app.command("create")
def subject_create(
    name: str,
    languages: str = typer.Option("he,en,pt", help="Comma-separated teaching languages"),
) -> None:
    def body(c: Container) -> None:
        codes = [code.strip() for code in languages.split(",") if code.strip()]
        subject = c.subject_service.get_or_create(name, codes)
        typer.echo(
            f"{subject.name} [{subject.state.value}] languages={','.join(subject.languages)} id={subject.id}"
        )

    _run(body)


@subject_app.command("list")
def subject_list() -> None:
    def body(c: Container) -> None:
        for subject in c.subject_service.list():
            typer.echo(
                f"{subject.name} [{subject.state.value}] "
                f"languages={','.join(subject.languages)} id={subject.id}"
            )

    _run(body)


@app.command()
def ingest(
    files: list[Path] = typer.Argument(..., exists=True, readable=True, help="PDF, image or text files"),
    subject: str = typer.Option(..., "--subject", "-s", help="Subject name; created if missing"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation"),
) -> None:
    """Register files as sources of a subject and run the ingestion pipeline on each."""

    def body(c: Container) -> None:
        c.check_ready()
        subj = c.subject_service.get_or_create(subject)

        estimate = estimate_ingest(
            page_count=sum(_estimated_pages(path) for path in files),
            model=c.settings.model_read_pages,
            prices=c.prices,
        )
        typer.echo(f"Estimate: {estimate.describe()} (embeddings extra, small)")
        if not yes:
            typer.confirm("Proceed?", abort=True)

        failures = 0
        for path in files:
            try:
                source = c.source_service.register(subj, path.name, path.read_bytes())
                c.job_runner.enqueue("ingest_source", {"source_id": str(source.id)})
                typer.echo(_describe(c.sources.get(source.id)))
            except Exception as exc:  # report and continue with the next file
                failures += 1
                typer.echo(f"{path.name}: FAILED {type(exc).__name__}: {exc}", err=True)
        if failures:
            raise typer.Exit(code=1)

    _run(body)


@source_app.command("list")
def source_list(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    def body(c: Container) -> None:
        for source in c.source_service.list(c.subject_service.require(subject)):
            typer.echo(f"{source.id}  {_describe(source)}")

    _run(body)


@source_app.command("delete")
def source_delete(source_id: UUID, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    def body(c: Container) -> None:
        source = c.sources.get(source_id)
        if not yes:
            typer.confirm(f"Delete {source.filename} and its pages and chunks?", abort=True)
        c.source_service.delete(source_id)
        typer.echo(f"deleted {source.filename}")

    _run(body)


@source_app.command("reingest")
def source_reingest(source_id: UUID, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    """Re-run the whole pipeline for one source (after fixing the file or the prompts)."""

    def body(c: Container) -> None:
        c.check_ready()
        source = c.sources.get(source_id)
        estimate = estimate_ingest(
            page_count=source.page_count or 1, model=c.settings.model_read_pages, prices=c.prices
        )
        typer.echo(f"Estimate: {estimate.describe()}")
        if not yes:
            typer.confirm("Proceed?", abort=True)
        updated = c.source_service.mark_for_reingest(source_id)
        c.job_runner.enqueue("ingest_source", {"source_id": str(updated.id)})
        typer.echo(_describe(c.sources.get(updated.id)))

    _run(body)


@app.command()
def export(
    subject: str = typer.Option(..., "--subject", "-s"),
    out: Path = typer.Option(Path("digest-export"), "--out", "-o"),
) -> None:
    """Write every source of a subject as a digest bundle under OUT."""

    def body(c: Container) -> None:
        subj = c.subject_service.require(subject)
        for source in c.source_service.list(subj):
            folder = c.export_import.export_source(source.id, out)
            typer.echo(f"{source.filename} -> {folder}")

    _run(body)


@app.command("import")
def import_bundle(
    bundle_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    subject: str = typer.Option(..., "--subject", "-s", help="Target subject; created if missing"),
) -> None:
    """Load one source bundle folder (the folder containing meta.json) into a subject."""

    def body(c: Container) -> None:
        c.check_ready()
        subj = c.subject_service.get_or_create(subject)
        source = c.export_import.import_source(subj, bundle_dir)
        typer.echo(_describe(source))

    _run(body)


@app.command()
def usage(subject: str | None = typer.Option(None, "--subject", "-s")) -> None:
    """Cost and token summary per purpose and model."""

    def body(c: Container) -> None:
        subject_id = c.subject_service.require(subject).id if subject else None
        typer.echo(c.usage_service.format_table(c.usage_service.summary(subject_id)))

    _run(body)


@app.command()
def generate(
    subject: str = typer.Option(..., "--subject", "-s"),
    language: list[str] = typer.Option(None, "--language", "-l", help="Repeatable; default: all enabled"),
    part: list[int] = typer.Option(
        None,
        "--part",
        "-p",
        help="Repeatable part positions; reuses the current outline. Default: all parts",
    ),
    content_only: bool = typer.Option(False, "--content-only", help="Keep the current outline and glossary"),
) -> None:
    """Generate outline, glossary, teaching text and question bank for a subject."""

    def body(c: Container) -> None:
        c.check_ready()
        subj = c.subject_service.require(subject)
        report = c.tutorial_service.generate(
            subj, languages=language or None, parts=part or None, content_only=content_only
        )
        typer.echo(f"{subj.name}: outline v{report.outline_version}{' (new)' if report.new_outline else ''}")
        for r in report.results:
            line = (
                f"  part {r.part_position} [{r.language}]: {r.content_status.value}, {r.questions} questions"
            )
            typer.echo(line + (f"  error: {r.error}" if r.error else ""))
        if report.failures:
            raise typer.Exit(code=1)

    _run(body)


@app.command()
def publish(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    """Lock sources and make the subject visible to students. Requires complete content in every language."""

    def body(c: Container) -> None:
        subj = c.subject_service.require(subject)
        published = c.tutorial_service.publish(subj)
        typer.echo(f"{published.name}: published outline v{published.current_outline_version}")

    _run(body)


@app.command()
def unpublish(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    """Return a published subject to draft so it can be regenerated."""

    def body(c: Container) -> None:
        draft = c.tutorial_service.unpublish(c.subject_service.require(subject))
        typer.echo(f"{draft.name}: {draft.state.value}")

    _run(body)


@tutorial_app.command("status")
def tutorial_status(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    """Report generation and publish readiness per language."""

    def body(c: Container) -> None:
        status = c.tutorial_service.status(c.subject_service.require(subject))
        typer.echo(
            f"{status.subject}: {status.state.value}, outline v{status.outline_version}, "
            f"published v{status.published_version}, {status.parts} parts"
        )
        for lang in status.languages:
            line = (
                f"  {lang.language}: {lang.parts_ready}/{lang.parts_total} parts ready, "
                f"{lang.questions} questions, complete: {'yes' if lang.complete else 'no'}"
            )
            if lang.failed:
                line += f", failed: {list(lang.failed)}"
            typer.echo(line)
        typer.echo(f"publishable: {'yes' if status.publishable else 'no'}")

    _run(body)


@tutorial_app.command("show")
def tutorial_show(
    subject: str = typer.Option(..., "--subject", "-s"),
    language: str = typer.Option(..., "--language", "-l"),
    part: int = typer.Option(0, "--part", "-p"),
) -> None:
    """Print a part's rendered teaching text as a student would receive it."""

    def body(c: Container) -> None:
        rendered = c.tutorial_service.rendered_part(c.subject_service.require(subject), language, part)
        typer.echo(f"# {rendered.title}\n")
        typer.echo(rendered.body)
        typer.echo("\n## Key points")
        for point in rendered.key_points:
            typer.echo(f"- {point}")

    _run(body)
