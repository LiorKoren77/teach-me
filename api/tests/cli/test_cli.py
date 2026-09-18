from __future__ import annotations

import pytest
from typer.testing import CliRunner

from teachme.container import Container
from teachme.settings import Settings
from tests.helpers import make_pdf

runner = CliRunner()


@pytest.fixture
def cli(db, migrated_database, tmp_path, monkeypatch):
    import teachme.cli.main as main

    settings = Settings(
        _env_file=None,
        database_url=migrated_database,
        llm_provider="fake",
        embeddings_provider="fake",
        reranker_provider="noop",
        file_store="local",
        local_files_dir=tmp_path / "files",
        digest_dir=tmp_path / "digest",
        pages_per_read_batch=2,
        pages_per_chunk_batch=2,
    )
    container = Container(settings)
    monkeypatch.setattr(main, "build_container", lambda: container)
    monkeypatch.setattr(container, "close", lambda: None)  # commands call close(); keep it open for the test
    pdf = tmp_path / "ch1.pdf"
    pdf.write_bytes(make_pdf(3))
    yield main.app, pdf, tmp_path
    Container.close(container)


def test_subject_create_and_list(cli):
    app, *_ = cli
    result = runner.invoke(app, ["subject", "create", "Geo", "--languages", "he,en"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["subject", "list"])
    assert "Geo" in result.output and "draft" in result.output and "he,en" in result.output


def test_ingest_export_usage_flow(cli):
    app, pdf, tmp_path = cli
    result = runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(pdf)])
    assert result.exit_code == 0, result.output
    assert "3 pages" in result.output and "ready" in result.output

    result = runner.invoke(app, ["source", "list", "--subject", "Geo"])
    assert "ch1.pdf" in result.output and "ready" in result.output

    result = runner.invoke(app, ["usage", "--subject", "Geo"])
    assert result.exit_code == 0 and "ingest.read_pages" in result.output

    result = runner.invoke(app, ["export", "--subject", "Geo", "--out", str(tmp_path / "exp")])
    assert result.exit_code == 0, result.output
    exported = [p for p in (tmp_path / "exp").rglob("meta.json")]
    assert len(exported) == 1

    result = runner.invoke(app, ["import", "--subject", "Geo copy", str(exported[0].parent)])
    assert result.exit_code == 0, result.output
    assert "ready" in result.output


def test_ingest_rejects_unknown_type(cli):
    app, pdf, tmp_path = cli
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"PK")
    result = runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(bad)])
    assert result.exit_code == 1 and "not accepted" in result.output
