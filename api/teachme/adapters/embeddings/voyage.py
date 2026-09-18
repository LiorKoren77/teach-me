from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import voyageai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from teachme.ports.embeddings import EmbeddingResult

# Names verified against the installed voyageai package; adjust here if a release renames them.
_TRANSIENT = (
    voyageai.error.RateLimitError,
    voyageai.error.ServiceUnavailableError,
    voyageai.error.APIConnectionError,
    voyageai.error.Timeout,
)


class VoyageEmbedder:
    name = "voyage"

    def __init__(
        self,
        model: str,
        dimension: int = 1024,
        client: Any | None = None,
        batch_size: int = 128,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.dimension = dimension
        self._client = client or voyageai.Client(api_key=api_key)
        self._batch_size = batch_size

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        vectors: list[list[float]] = []
        tokens = 0
        for start in range(0, len(texts), self._batch_size):
            batch = self._embed(list(texts[start : start + self._batch_size]), "document")
            vectors.extend(batch.vectors)
            tokens += batch.tokens
        return EmbeddingResult(vectors=vectors, tokens=tokens)

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._embed([text], "query")

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        wait=wait_exponential(multiplier=1, min=5, max=120),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _embed(self, texts: list[str], input_type: str) -> EmbeddingResult:
        response = self._client.embed(texts, model=self.model, input_type=input_type)
        return EmbeddingResult(
            vectors=[list(v) for v in response.embeddings],
            tokens=int(response.total_tokens),
        )
