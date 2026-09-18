from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from teachme.adapters.llm.anthropic import AnthropicLLM
from teachme.ports.llm import ContentPart, LLMOutputTruncated, LLMRefused, StructuredRequest


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


def _message(stop_reason="end_turn", parsed=Answer(value=7)):
    usage = SimpleNamespace(input_tokens=120, output_tokens=8, cache_read_input_tokens=100, cache_creation_input_tokens=None)
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage, model="claude-opus-5")


def _request():
    return StructuredRequest(
        purpose="test", model="claude-opus-5", system="sys",
        parts=(ContentPart.of_document(b"%PDF-1.4", "application/pdf"), ContentPart.of_text("Read it")),
        max_tokens=4000, effort="low",
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
    assert kwargs["thinking"] == {"type": "adaptive"} and kwargs["output_config"] == {"effort": "low"}
    assert kwargs["output_format"] is Answer
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert content[0]["source"]["data"] == "JVBERi0xLjQ="
    assert content[1] == {"type": "text", "text": "Read it"}


def test_refusal_and_truncation_raise():
    with pytest.raises(LLMRefused):
        AnthropicLLM(client=_StubClient(_message(stop_reason="refusal"))).generate_structured(_request(), Answer)
    with pytest.raises(LLMOutputTruncated):
        AnthropicLLM(client=_StubClient(_message(stop_reason="max_tokens"))).generate_structured(_request(), Answer)


def test_capabilities_include_pdf_and_images():
    caps = AnthropicLLM(client=_StubClient(_message())).capabilities()
    assert {"application/pdf", "image/png", "image/jpeg", "text/plain", "text/markdown"} <= caps.media_types
