from __future__ import annotations

import pytest
from pydantic import ValidationError

from teachme.settings import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Settings reads os.environ directly; strip every variable it knows about first so
    a developer's shell (or .env) can never make a test pass or fail non-deterministically."""
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


def test_defaults_are_local_and_anthropic(monkeypatch):
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "anthropic"
    assert settings.file_store == "local"
    assert settings.enabled_languages == ["he", "en", "pt"]
    assert settings.model_read_pages == "claude-opus-5"


def test_default_database_url_uses_docker_compose_port():
    settings = Settings(_env_file=None)
    assert settings.database_url.endswith(":5433/teachme")


def test_credential_fields_are_secret_and_optional():
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key is None
    settings = Settings(_env_file=None, anthropic_api_key="sk-x")
    assert settings.anthropic_api_key.get_secret_value() == "sk-x"


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
