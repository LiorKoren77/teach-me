from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from teachme.adapters.llm.anthropic import AnthropicLLM
from teachme.ports.llm import (
    ContentPart,
    LLMOutputTruncated,
    LLMParseError,
    LLMRefused,
    StructuredRequest,
    TextRequest,
)

_MISSING = object()


class Answer(BaseModel):
    value: int


class _Stream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _StubClient:
    """Records the kwargs of messages.stream and returns a canned final message."""

    def __init__(self, message):
        self.calls = []
        self.messages = SimpleNamespace(stream=self._stream)
        self._message = message

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _Stream(self._message)


def _message(stop_reason="end_turn", parsed=_MISSING):
    parsed = parsed if parsed is not _MISSING else Answer(value=7)
    usage = SimpleNamespace(
        input_tokens=120, output_tokens=8, cache_read_input_tokens=100, cache_creation_input_tokens=None
    )
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage, model="claude-opus-5")


def _request():
    return StructuredRequest(
        purpose="test",
        model="claude-opus-5",
        system="sys",
        parts=(ContentPart.of_document(b"%PDF-1.4", "application/pdf"), ContentPart.of_text("Read it")),
        max_tokens=4000,
        effort="low",
    )


def test_builds_request_and_returns_parsed_output():
    client = _StubClient(_message())
    llm = AnthropicLLM(client=client)
    result = llm.generate_structured(_request(), Answer)
    assert result.output == Answer(value=7)
    assert result.usage.input_tokens == 120 and result.usage.cache_read_tokens == 100
    assert result.usage.cache_write_tokens == 0 and result.model == "claude-opus-5"
    kwargs = client.calls[0]
    assert kwargs["model"] == "claude-opus-5" and kwargs["max_tokens"] == 4000
    # a low-effort call's budget is too small to also carry an adaptive thinking block
    assert kwargs["thinking"] == {"type": "disabled"} and kwargs["output_config"] == {"effort": "low"}
    assert kwargs["output_format"] is Answer
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert content[0]["source"]["data"] == "JVBERi0xLjQ="
    assert content[1] == {"type": "text", "text": "Read it"}


def test_thinking_stays_adaptive_above_low_effort():
    client = _StubClient(_message())
    request = StructuredRequest(
        purpose="test",
        model="claude-opus-5",
        system="sys",
        parts=(ContentPart.of_text("x"),),
        effort="high",
    )
    AnthropicLLM(client=client).generate_structured(request, Answer)
    assert client.calls[0]["thinking"] == {"type": "adaptive"}


def test_refusal_and_truncation_raise():
    with pytest.raises(LLMRefused):
        llm = AnthropicLLM(client=_StubClient(_message(stop_reason="refusal")))
        llm.generate_structured(_request(), Answer)
    with pytest.raises(LLMOutputTruncated):
        llm = AnthropicLLM(client=_StubClient(_message(stop_reason="max_tokens")))
        llm.generate_structured(_request(), Answer)


def test_missing_parsed_output_is_parse_error():
    with pytest.raises(LLMParseError, match="end_turn"):
        llm = AnthropicLLM(client=_StubClient(_message(parsed=None)))
        llm.generate_structured(_request(), Answer)


def test_capabilities_include_pdf_and_images():
    caps = AnthropicLLM(client=_StubClient(_message())).capabilities()
    assert {"application/pdf", "image/png", "image/jpeg", "text/plain", "text/markdown"} <= caps.media_types


def test_document_part_without_data_raises():
    request = StructuredRequest(
        purpose="test",
        model="claude-opus-5",
        system="sys",
        parts=(ContentPart(kind="document", data=None, media_type=None),),
        max_tokens=4000,
        effort="low",
    )
    with pytest.raises(ValueError, match="document"):
        AnthropicLLM(client=_StubClient(_message())).generate_structured(request, Answer)


def test_cached_context_becomes_first_system_block_with_cache_control():
    client = _StubClient(_message())
    request = StructuredRequest(
        purpose="t",
        model="claude-opus-5",
        system="instructions",
        parts=(ContentPart.of_text("x"),),
        cached_context="<corpus>big text</corpus>",
    )
    AnthropicLLM(client=client).generate_structured(request, Answer)
    system = client.calls[0]["system"]
    assert system[0] == {
        "type": "text",
        "text": "<corpus>big text</corpus>",
        "cache_control": {"type": "ephemeral"},
    }
    assert system[1] == {"type": "text", "text": "instructions"}


def test_without_cached_context_the_single_system_block_is_cached():
    client = _StubClient(_message())
    AnthropicLLM(client=client).generate_structured(_request(), Answer)
    system = client.calls[0]["system"]
    assert len(system) == 1 and system[0]["cache_control"] == {"type": "ephemeral"}


class _TextStream:
    """Stands in for the SDK's MessageStream: text deltas then the accumulated final message."""

    def __init__(self, chunks, message):
        self._chunks = chunks
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        yield from self._chunks

    def get_final_message(self):
        return self._message


def _text_client(message):
    client = _StubClient(message)

    def stream(**kwargs):
        client.calls.append(kwargs)
        return _TextStream(["Hel", "lo"], message)

    client.messages = SimpleNamespace(stream=stream)
    return client


def _text_request(**overrides):
    base = dict(
        purpose="t", model="claude-opus-5", system="s", parts=(ContentPart.of_text("x"),), max_tokens=6000
    )
    return TextRequest(**{**base, **overrides})


def test_stream_text_yields_deltas_then_reports_usage():
    message = _message()
    client = _text_client(message)
    collected = []
    result = AnthropicLLM(client=client).stream_text(_text_request(), on_delta=collected.append)
    assert collected == ["Hel", "lo"] and result.text == "Hello"
    assert result.usage.input_tokens == 120 and not result.truncated
    kwargs = client.calls[0]
    assert kwargs["model"] == "claude-opus-5" and kwargs["max_tokens"] == 6000
    assert kwargs["thinking"] == {"type": "adaptive"} and kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["system"] == [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["messages"] == [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
    assert "output_format" not in kwargs


def test_stream_text_reports_truncation_instead_of_raising():
    """Prose that ran out of budget is still prose the student can read, so the caller decides
    what to do with it - unlike a structured output, which would not parse."""
    client = _text_client(_message(stop_reason="max_tokens"))
    result = AnthropicLLM(client=client).stream_text(_text_request(), on_delta=lambda d: None)
    assert result.text == "Hello" and result.truncated


def test_stream_text_raises_on_a_refusal():
    client = _text_client(_message(stop_reason="refusal"))
    with pytest.raises(LLMRefused):
        AnthropicLLM(client=client).stream_text(_text_request(), on_delta=lambda d: None)
