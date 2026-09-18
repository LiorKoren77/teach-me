from __future__ import annotations

import base64
from typing import Any

from anthropic import Anthropic

from teachme.ports.llm import (
    ContentPart,
    LLMCapabilities,
    LLMOutputTruncated,
    LLMParseError,
    LLMRefused,
    LLMUsage,
    OnDelta,
    StructuredRequest,
    StructuredResult,
    T,
    TextRequest,
    TextResult,
)

MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "text/plain",
        "text/markdown",
    }
)


class AnthropicLLM:
    """Claude through the official SDK. Always streams so large outputs never hit HTTP timeouts,
    and always requests structured output so callers get a validated pydantic object."""

    name = "anthropic"
    MEDIA_TYPES = MEDIA_TYPES

    def __init__(self, client: Anthropic | None = None, api_key: str | None = None) -> None:
        # api_key None lets the SDK resolve ANTHROPIC_API_KEY or federation from the environment.
        self._client = client or Anthropic(api_key=api_key, max_retries=5, timeout=600.0)

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(media_types=MEDIA_TYPES)

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]:
        with self._client.messages.stream(
            model=request.model,
            max_tokens=request.max_tokens,
            system=_system_blocks(request),
            thinking=_thinking(request),
            output_config={"effort": request.effort},
            messages=[{"role": "user", "content": [_to_block(part) for part in request.parts]}],
            output_format=schema,
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise LLMRefused(f"{request.purpose}: model refused the request")
        if message.stop_reason == "max_tokens":
            raise LLMOutputTruncated(f"{request.purpose}: output exceeded max_tokens={request.max_tokens}")
        output = message.parsed_output
        if output is None:
            raise LLMParseError(
                f"{request.purpose}: no parseable {schema.__name__} in response"
                f" (stop_reason={message.stop_reason})"
            )

        usage = LLMUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_read_tokens=message.usage.cache_read_input_tokens or 0,
            cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
        )
        return StructuredResult(output=output, usage=usage, model=message.model)

    def stream_text(self, request: TextRequest, *, on_delta: OnDelta) -> TextResult:
        """Prose as it is produced: `text_stream` yields only the text deltas (thinking blocks are
        skipped by the SDK), and the accumulated final message carries the usage."""
        pieces: list[str] = []
        with self._client.messages.stream(
            model=request.model,
            max_tokens=request.max_tokens,
            system=_system_blocks(request),
            thinking=_thinking(request),
            output_config={"effort": request.effort},
            messages=[{"role": "user", "content": [_to_block(part) for part in request.parts]}],
        ) as stream:
            for delta in stream.text_stream:
                pieces.append(delta)
                on_delta(delta)
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise LLMRefused(f"{request.purpose}: model refused the request")
        usage = LLMUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_read_tokens=message.usage.cache_read_input_tokens or 0,
            cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
        )
        return TextResult(text="".join(pieces), usage=usage, model=message.model)


def _thinking(request: StructuredRequest | TextRequest) -> dict[str, str]:
    """Adaptive thinking is billed only for what it produces, but it still counts against
    max_tokens: at low effort the budget is small enough that a thinking block alone can
    exhaust it and truncate the answer, so low effort turns thinking off."""
    return {"type": "disabled"} if request.effort == "low" else {"type": "adaptive"}


def _system_blocks(request: StructuredRequest | TextRequest) -> list[dict[str, Any]]:
    """Cache the stable prefix. With a cached_context the instructions follow it uncached, so the
    same corpus is reused by every generation step; without one the instructions are the prefix."""
    if request.cached_context:
        return [
            {"type": "text", "text": request.cached_context, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": request.system},
        ]
    return [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}]


def _to_block(part: ContentPart) -> dict[str, Any]:
    if part.kind == "text":
        return {"type": "text", "text": part.text or ""}
    if part.data is None or part.media_type is None:
        raise ValueError(f"{part.kind} part needs data and media_type")
    encoded = base64.standard_b64encode(part.data).decode("ascii")
    source = {"type": "base64", "media_type": part.media_type, "data": encoded}
    return {"type": "document" if part.kind == "document" else "image", "source": source}
