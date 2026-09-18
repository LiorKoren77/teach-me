from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from teachme.domain.models import Page
from teachme.ingestion.prompts import load_prompt
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest

SAMPLE_PAGES = 3
SAMPLE_CHARS = 6000


class DetectedLanguage(BaseModel):
    code: str = Field(description="ISO 639-1 two-letter code, or 'und'")
    name: str = Field(description="English name of the language")


def detect_language(llm: LLMProvider, model: str, pages: Sequence[Page]) -> str | None:
    """Two-letter code of the dominant body-text language, from a sample of the first pages."""
    sample = "\n\n".join(page.text for page in pages[:SAMPLE_PAGES])[:SAMPLE_CHARS].strip()
    if not sample:
        return None
    request = StructuredRequest(
        purpose="ingest.detect_language",
        model=model,
        system=load_prompt("detect_language"),
        parts=(ContentPart.of_text(sample),),
        max_tokens=256,
        effort="low",
    )
    return llm.generate_structured(request, DetectedLanguage).output.code.lower()
