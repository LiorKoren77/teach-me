from __future__ import annotations

import pytest
from pydantic import BaseModel

from teachme.adapters.llm.fake import FakeLLM
from teachme.ports.llm import ContentPart, LLMParseError, StructuredRequest


class Out(BaseModel):
    echo: str


def _req(text):
    return StructuredRequest(purpose="t", model="m", system="s", parts=(ContentPart.of_text(text),))


def test_responder_is_called_with_request_and_calls_are_recorded():
    fake = FakeLLM({Out: lambda req: Out(echo=req.parts[0].text.upper())})
    result = fake.generate_structured(_req("hi"), Out)
    assert result.output.echo == "HI" and result.model == "fake-model"
    assert fake.calls[0].purpose == "t"


def test_missing_responder_is_a_parse_error():
    with pytest.raises(LLMParseError):
        FakeLLM({}).generate_structured(_req("x"), Out)


def test_capabilities_default_to_pdf_and_text():
    assert "application/pdf" in FakeLLM({}).capabilities().media_types


def test_set_responder_installs_and_replaces_a_responder():
    fake = FakeLLM({})
    fake.set_responder(Out, lambda req: Out(echo="first"))
    assert fake.generate_structured(_req("x"), Out).output.echo == "first"
    fake.set_responder(Out, lambda req: Out(echo="second"))
    assert fake.generate_structured(_req("x"), Out).output.echo == "second"


def test_fake_records_cached_context():
    fake = FakeLLM({Out: lambda req: Out(echo=req.cached_context or "")})
    req = StructuredRequest(
        purpose="t", model="m", system="s", parts=(ContentPart.of_text("x"),), cached_context="C"
    )
    assert fake.generate_structured(req, Out).output.echo == "C"
