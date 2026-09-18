from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

import typer

from teachme.adapters.db.migrate import apply_migrations
from teachme.container import Container
from teachme.domain.models import Source
from teachme.ingestion.errors import ExtractionError
from teachme.ingestion.estimate import estimate_ingest
from teachme.ingestion.pdf_pages import page_count

app = typer.Typer(no_args_is_help=True, help="teach-me operator commands")
subject_app = typer.Typer(no_args_is_help=True, help="Manage subjects")
source_app = typer.Typer(no_args_is_help=True, help="Manage sources")
app.add_typer(subject_app, name="subject")
app.add_typer(source_app, name="source")


def build_container() -> Container:
    """Patched in tests. One Container per command invocation."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return Container()


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
    c = build_container()
    applied = apply_migrations(c.conn)
    typer.echo(f"applied: {applied}" if applied else "schema already current")
    c.close()


@subject_app.command("create")
def subject_create(
    name: str,
    languages: str = typer.Option("he,en,pt", help="Comma-separated teaching languages"),
) -> None:
    c = build_container()
    codes = [code.strip() for code in languages.split(",") if code.strip()]
    subject = c.subject_service.get_or_create(name, codes)
    typer.echo(
        f"{subject.name} [{subject.state.value}] languages={','.join(subject.languages)} id={subject.id}"
    )
    c.close()


@subject_app.command("list")
def subject_list() -> None:
    c = build_container()
    for subject in c.subject_service.list():
        typer.echo(
            f"{subject.name} [{subject.state.value}] languages={','.join(subject.languages)} id={subject.id}"
        )
    c.close()


@app.command()
def ingest(
    files: list[Path] = typer.Argument(  # noqa: B008 (typer builds the default at import time)
        ..., exists=True, readable=True, help="PDF, image or text files"
    ),
    subject: str = typer.Option(..., "--subject", "-s", help="Subject name; created if missing"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation"),
) -> None:
    """Register files as sources of a subject and run the ingestion pipeline on each."""
    c = build_container()
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
    c.close()
    if failures:
        raise typer.Exit(code=1)


@source_app.command("list")
def source_list(subject: str = typer.Option(..., "--subject", "-s")) -> None:
    c = build_container()
    for source in c.source_service.list(c.subject_service.require(subject)):
        typer.echo(f"{source.id}  {_describe(source)}")
    c.close()


@source_app.command("delete")
def source_delete(source_id: UUID, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    c = build_container()
    source = c.sources.get(source_id)
    if not yes:
        typer.confirm(f"Delete {source.filename} and its pages and chunks?", abort=True)
    c.source_service.delete(source_id)
    typer.echo(f"deleted {source.filename}")
    c.close()


@source_app.command("reingest")
def source_reingest(source_id: UUID, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    """Re-run the whole pipeline for one source (after fixing the file or the prompts)."""
    c = build_container()
    c.check_ready()
    source = c.source_service.mark_for_reingest(source_id)
    estimate = estimate_ingest(
        page_count=source.page_count or 1, model=c.settings.model_read_pages, prices=c.prices
    )
    typer.echo(f"Estimate: {estimate.describe()}")
    if not yes:
        typer.confirm("Proceed?", abort=True)
    c.job_runner.enqueue("ingest_source", {"source_id": str(source.id)})
    typer.echo(_describe(c.sources.get(source.id)))
    c.close()


@app.command()
def export(
    subject: str = typer.Option(..., "--subject", "-s"),
    out: Path = typer.Option(Path("digest-export"), "--out", "-o"),  # noqa: B008
) -> None:
    """Write every source of a subject as a digest bundle under OUT."""
    c = build_container()
    subj = c.subject_service.require(subject)
    for source in c.source_service.list(subj):
        folder = c.export_import.export_source(source.id, out)
        typer.echo(f"{source.filename} -> {folder}")
    c.close()


@app.command("import")
def import_bundle(
    bundle_dir: Path = typer.Argument(..., exists=True, file_okay=False),  # noqa: B008
    subject: str = typer.Option(..., "--subject", "-s", help="Target subject; created if missing"),
) -> None:
    """Load one source bundle folder (the folder containing meta.json) into a subject."""
    c = build_container()
    c.check_ready()
    subj = c.subject_service.get_or_create(subject)
    source = c.export_import.import_source(subj, bundle_dir)
    typer.echo(_describe(source))
    c.close()


@app.command()
def usage(subject: str | None = typer.Option(None, "--subject", "-s")) -> None:
    """Cost and token summary per purpose and model."""
    c = build_container()
    subject_id = c.subject_service.require(subject).id if subject else None
    typer.echo(c.usage_service.format_table(c.usage_service.summary(subject_id)))
    c.close()
