from __future__ import annotations

from teachme.ports.llm import ContentPart, LLMUsage, StructuredRequest


def test_content_part_constructors():
    text = ContentPart.of_text("hello")
    doc = ContentPart.of_document(b"%PDF", "application/pdf")
    img = ContentPart.of_image(b"\x89PNG", "image/png")
    assert text.kind == "text" and text.text == "hello"
    assert doc.kind == "document" and doc.media_type == "application/pdf" and doc.text is None
    assert img.kind == "image" and img.data == b"\x89PNG"


def test_request_defaults():
    req = StructuredRequest(purpose="test", model="claude-opus-5", system="s", parts=(ContentPart.of_text("x"),))
    assert req.max_tokens == 16000
    assert req.effort == "medium"


def test_usage_totals():
    usage = LLMUsage(input_tokens=10, output_tokens=5, cache_read_tokens=3, cache_write_tokens=2)
    assert usage.total_input == 15
