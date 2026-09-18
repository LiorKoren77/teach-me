from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from teachme.adapters.embeddings.voyage import VoyageEmbedder
from teachme.adapters.llm.anthropic import AnthropicLLM
from teachme.adapters.reranker.voyage import VoyageReranker
from teachme.ports.llm import ContentPart, StructuredRequest
from teachme.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call real providers"
)


class Capital(BaseModel):
    country: str
    capital: str


def test_anthropic_structured_call_returns_usage():
    settings = Settings()
    request = StructuredRequest(
        purpose="live.smoke",
        model=settings.model_detect_language,
        system="Answer precisely.",
        parts=(ContentPart.of_text("What is the capital of Portugal? Return country and capital."),),
        max_tokens=512,
        effort="low",
    )
    result = AnthropicLLM().generate_structured(request, Capital)
    assert result.output.capital.lower() == "lisbon"
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
    print("anthropic usage:", result.usage, result.model)


def test_voyage_embedding_dimension_matches_schema():
    settings = Settings()
    embedder = VoyageEmbedder(model=settings.embedding_model)
    result = embedder.embed_documents(["A biosphere is the global sum of all ecosystems."])
    assert len(result.vectors[0]) == 1024, "voyage-4 dimension changed; chunks.embedding is vector(1024)"
    assert result.tokens > 0
    order = VoyageReranker(model=settings.rerank_model).rerank(
        "what is a biosphere", ["ecosystems", "rocks"], 2
    )
    assert order[0] == 0
