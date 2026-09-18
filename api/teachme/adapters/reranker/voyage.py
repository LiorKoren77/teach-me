from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import voyageai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_TRANSIENT = (
    voyageai.error.RateLimitError,
    voyageai.error.ServiceUnavailableError,
    voyageai.error.APIConnectionError,
    voyageai.error.Timeout,
)


class VoyageReranker:
    name = "voyage"

    def __init__(self, model: str, client: Any | None = None, api_key: str | None = None) -> None:
        self.model = model
        self._client = client or voyageai.Client(api_key=api_key)

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        wait=wait_exponential(multiplier=1, min=5, max=120),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def rerank(self, query: str, documents: Sequence[str], top_k: int) -> list[int]:
        if not documents:
            return []
        response = self._client.rerank(query=query, documents=list(documents), model=self.model, top_k=top_k)
        return [item.index for item in response.results]
