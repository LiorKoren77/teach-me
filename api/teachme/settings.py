from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from teachme.domain.languages import LANGUAGES


class Settings(BaseSettings):
    """Every configurable value in one place. Nothing else reads os.environ."""

    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    # 5433: a native Postgres occupies 5432 on the dev machine; docker-compose maps to 5433
    database_url: str = "postgresql://teachme:teachme@localhost:5433/teachme"

    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    embeddings_provider: Literal["voyage", "fake"] = "voyage"
    reranker_provider: Literal["voyage", "noop"] = "voyage"
    file_store: Literal["local", "vercel_blob", "s3"] = "local"
    job_runner: Literal["inprocess", "sqs"] = "inprocess"

    local_files_dir: Path = Path("data/files")
    digest_dir: Path = Path("digest")
    write_local_bundle: bool = True
    blob_prefix: str = "teach-me"
    aws_region: str = "eu-central-1"
    s3_bucket: str | None = None
    sqs_queue_url: str | None = None

    model_read_pages: str = "claude-opus-5"
    model_detect_language: str = "claude-opus-5"
    model_contextualize: str = "claude-opus-5"
    model_generation: str = "claude-opus-5"
    model_grader: str = "claude-sonnet-5"
    model_relevance_check: str = "claude-haiku-4-5"
    model_reexplain: str = "claude-opus-5"
    embedding_model: str = "voyage-4"
    rerank_model: str = "rerank-2.5"

    enabled_languages: list[str] = ["he", "en", "pt"]
    allowed_upload_types: list[str] | None = None
    max_pages_per_source: int = 400
    pages_per_read_batch: int = 6
    pages_per_chunk_batch: int = 6
    max_answer_chars: int = 1500
    max_answers_per_minute: int = 20
    max_rejections_per_question: int = 2
    reinforce_sections_cap: int = 3

    # Credentials, passed explicitly to adapters instead of adapters reading os.environ themselves.
    anthropic_api_key: SecretStr | None = None
    voyage_api_key: SecretStr | None = None
    blob_read_write_token: SecretStr | None = None

    @field_validator("enabled_languages")
    @classmethod
    def _known_languages(cls, value: list[str]) -> list[str]:
        unknown = [code for code in value if code not in LANGUAGES]
        if unknown:
            raise ValueError(f"unsupported languages: {unknown}; supported: {sorted(LANGUAGES)}")
        return value
