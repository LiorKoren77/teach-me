from __future__ import annotations


def test_db_fixture_sets_a_short_lock_timeout(db):
    row = db.execute("SHOW lock_timeout").fetchone()
    assert row["lock_timeout"] == "15s"


def test_make_container_pins_settings_shell_vars_cannot_change(make_container):
    container = make_container()
    assert container.settings.write_local_bundle is True
    assert container.settings.job_runner == "inprocess"
    assert container.settings.enabled_languages == ["he", "en", "pt"]
    assert container.settings.allowed_upload_types is None
    # usable immediately; the fixture closes it in teardown, even if the test fails first.
    container.check_ready()


def test_make_container_allows_overrides(make_container):
    container = make_container(job_runner="inprocess", allowed_upload_types=["application/pdf"])
    assert container.settings.allowed_upload_types == ["application/pdf"]
