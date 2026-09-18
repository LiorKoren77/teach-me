from __future__ import annotations

import pytest
from typer.testing import CliRunner

from teachme.adapters.db.migrate import SchemaOutOfDate
from teachme.container import Container
from teachme.generation.teaching import TeachingOut
from teachme.ports.llm import LLMError
from teachme.repositories.outlines import OutlineVersionConflict
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
    monkeypatch.setattr(main, "build_container", lambda *a, **kw: container)
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


def test_reingest_asks_before_changing_the_source(cli):
    app, pdf, tmp_path = cli
    result = runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(pdf)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["source", "list", "--subject", "Geo"])
    source_id = result.output.split()[0]

    result = runner.invoke(app, ["source", "reingest", source_id], input="n\n")
    assert result.exit_code == 1

    result = runner.invoke(app, ["source", "list", "--subject", "Geo"])
    assert ": ready" in result.output


def test_ingest_rejects_unknown_type(cli):
    app, pdf, tmp_path = cli
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"PK")
    result = runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(bad)])
    assert result.exit_code == 1 and "not accepted" in result.output


def test_source_list_reports_a_missing_subject_plainly(cli):
    app, *_ = cli
    result = runner.invoke(app, ["source", "list", "--subject", "Nope"])
    assert result.exit_code == 1
    assert "error: subject Nope not found" in result.output
    assert "Traceback" not in result.output


def test_commands_refuse_to_run_against_an_out_of_date_schema(migrated_database, tmp_path, monkeypatch):
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
    )
    monkeypatch.setattr(main, "Container", lambda *a, **kw: Container(settings))

    def out_of_date(conn):
        raise SchemaOutOfDate(["0001_initial"])

    monkeypatch.setattr(main, "ensure_schema_current", out_of_date)

    result = runner.invoke(main.app, ["subject", "list"])

    assert result.exit_code == 1
    assert "teachme migrate" in result.output
    assert "Traceback" not in result.output


def test_ingest_survives_a_corrupt_pdf(cli):
    app, pdf, tmp_path = cli
    good = tmp_path / "good.pdf"
    good.write_bytes(make_pdf(2))
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")

    result = runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(good), str(bad)])

    assert result.exit_code == 1
    assert "good.pdf: ready" in result.output
    assert "bad.pdf: FAILED" in result.output

    result = runner.invoke(app, ["source", "list", "--subject", "Geo"])
    assert result.output.count(": ready") == 1


def test_generate_publish_show_flow(cli):
    app, pdf, tmp_path = cli
    assert runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(pdf)]).exit_code == 0
    result = runner.invoke(app, ["generate", "--subject", "Geo"])
    assert result.exit_code == 0, result.output
    assert "outline v1" in result.output and "he" in result.output and "ready" in result.output

    result = runner.invoke(app, ["tutorial", "status", "--subject", "Geo"])
    assert result.exit_code == 0 and "publishable: yes" in result.output

    result = runner.invoke(app, ["publish", "--subject", "Geo"])
    assert result.exit_code == 0 and "published" in result.output

    result = runner.invoke(app, ["tutorial", "show", "--subject", "Geo", "--language", "he", "--part", "0"])
    assert result.exit_code == 0 and "Fake part title" in result.output and "{{term:" not in result.output

    result = runner.invoke(app, ["generate", "--subject", "Geo"])
    assert result.exit_code == 1 and "published" in result.output

    result = runner.invoke(app, ["unpublish", "--subject", "Geo"])
    assert result.exit_code == 0 and "draft" in result.output
    result = runner.invoke(
        app, ["generate", "--subject", "Geo", "--language", "he", "--part", "0", "--content-only"]
    )
    assert result.exit_code == 0 and "outline v1" in result.output


def test_generate_rejects_an_unknown_part(cli):
    app, pdf, tmp_path = cli
    assert runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(pdf)]).exit_code == 0
    assert runner.invoke(app, ["generate", "--subject", "Geo"]).exit_code == 0
    result = runner.invoke(app, ["generate", "--subject", "Geo", "--part", "9"])
    assert result.exit_code == 1
    assert "error: no such parts: [9]" in result.output


def test_tutorial_status_counts_ready_parts_and_names_failed_parts(cli):
    import teachme.cli.main as main

    app, pdf, tmp_path = cli
    multipart = tmp_path / "ch2.pdf"
    multipart.write_bytes(make_pdf(6))
    assert runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(multipart)]).exit_code == 0
    assert runner.invoke(app, ["generate", "--subject", "Geo", "--language", "he"]).exit_code == 0
    result = runner.invoke(app, ["generate", "--subject", "Geo", "--language", "en", "--part", "1"])
    assert result.exit_code == 0 and "outline v1" in result.output

    result = runner.invoke(app, ["tutorial", "status", "--subject", "Geo"])
    assert result.exit_code == 0, result.output
    assert "he: 2/2 parts ready" in result.output
    assert "en: 1/2 parts ready" in result.output
    assert "failed" not in result.output

    def boom(request):
        raise LLMError("teaching service down")

    main.build_container().llm.inner.set_responder(TeachingOut, boom)
    result = runner.invoke(app, ["generate", "--subject", "Geo", "--language", "he", "--part", "0"])
    assert result.exit_code == 1

    result = runner.invoke(app, ["tutorial", "status", "--subject", "Geo"])
    assert "he: 1/2 parts ready" in result.output and "failed: [0]" in result.output


def test_generate_reports_an_outline_version_conflict_as_an_operator_error(cli, monkeypatch):
    import teachme.cli.main as main

    app, pdf, tmp_path = cli
    assert runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(pdf)]).exit_code == 0

    def boom(*args, **kwargs):
        raise OutlineVersionConflict("another generate won the race for version 2")

    monkeypatch.setattr(main.build_container().tutorial_service, "generate", boom)
    result = runner.invoke(app, ["generate", "--subject", "Geo"])
    assert result.exit_code == 1 and "error: another generate won the race" in result.output


def test_tutorial_show_names_the_outline_version_and_can_render_a_draft(cli):
    app, pdf, tmp_path = cli
    assert runner.invoke(app, ["ingest", "--subject", "Geo", "--yes", str(pdf)]).exit_code == 0
    assert runner.invoke(app, ["generate", "--subject", "Geo"]).exit_code == 0
    assert runner.invoke(app, ["publish", "--subject", "Geo"]).exit_code == 0

    result = runner.invoke(app, ["tutorial", "show", "--subject", "Geo", "--language", "he"])
    assert result.exit_code == 0, result.output
    assert "outline v1 (published)" in result.output

    assert runner.invoke(app, ["unpublish", "--subject", "Geo"]).exit_code == 0
    # v2 is generated for one language only, so it stays a draft and publish falls back to v1
    assert runner.invoke(app, ["generate", "--subject", "Geo", "--language", "he"]).exit_code == 0
    result = runner.invoke(app, ["publish", "--subject", "Geo"])
    assert result.exit_code == 0 and "outline v1" in result.output

    result = runner.invoke(app, ["tutorial", "show", "--subject", "Geo", "--language", "he"])
    assert result.exit_code == 0 and "outline v1 (published)" in result.output
    result = runner.invoke(app, ["tutorial", "show", "--subject", "Geo", "--language", "he", "--draft"])
    assert result.exit_code == 0, result.output
    assert "outline v2 (draft)" in result.output
