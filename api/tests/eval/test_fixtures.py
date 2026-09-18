from __future__ import annotations

import json

import pytest

from teachme.eval.fixtures import FIXTURES_DIR, FixtureError, load_cases


def test_the_shipped_fixtures_load_and_cover_the_three_languages():
    cases = load_cases()
    assert [case.spec.language for case in cases] == ["en", "he", "pt"]
    for case in cases:
        text = case.source.decode("utf-8")
        assert 300 < len(text.split()) < 1200
        assert text.count("> **[Figure:") == 2
        assert case.spec.teach_in[0] == case.spec.language
        assert {a.expected_grade for a in case.spec.answers} >= {"correct", "incorrect", "junk"}


def test_a_language_filter_selects_one_fixture_and_an_unknown_one_is_an_error():
    assert [case.spec.language for case in load_cases(languages=["he"])] == ["he"]
    with pytest.raises(FixtureError, match="no fixture"):
        load_cases(languages=["xx"])


def test_a_fixture_folder_is_read_as_yaml_too(tmp_path):
    yaml = pytest.importorskip("yaml")
    spec = json.loads((FIXTURES_DIR / "en" / "expected.json").read_text(encoding="utf-8"))
    folder = tmp_path / "en"
    folder.mkdir()
    (folder / "source.md").write_text("text", encoding="utf-8")
    (folder / "expected.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    (case,) = load_cases(tmp_path)
    assert case.spec == load_cases(languages=["en"])[0].spec


def test_a_folder_without_a_spec_or_a_source_is_an_error(tmp_path):
    (tmp_path / "en").mkdir()
    with pytest.raises(FixtureError, match="expected"):
        load_cases(tmp_path)
    (tmp_path / "en" / "expected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FixtureError):
        load_cases(tmp_path)
