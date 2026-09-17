from __future__ import annotations

import pytest
from pydantic import ValidationError

from teachme.settings import Settings


def test_defaults_are_local_and_anthropic(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "anthropic"
    assert settings.file_store == "local"
    assert settings.enabled_languages == ["he", "en", "pt"]
    assert settings.model_read_pages == "claude-opus-5"


def test_reads_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ENABLED_LANGUAGES", '["he"]')
    monkeypatch.setenv("MAX_PAGES_PER_SOURCE", "12")
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "fake"
    assert settings.enabled_languages == ["he"]
    assert settings.max_pages_per_source == 12


def test_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_rejects_unknown_language(monkeypatch):
    monkeypatch.setenv("ENABLED_LANGUAGES", '["he","xx"]')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
