from __future__ import annotations

import pytest

from teachme.ingestion.prompts import load_prompt


def test_prompts_load_and_are_non_empty():
    for name in ("read_pages", "detect_language", "contextualize"):
        text = load_prompt(name)
        assert len(text) > 100


def test_contextualize_prompt_has_placeholders():
    text = load_prompt("contextualize")
    assert "{subject}" in text and "{source}" in text


def test_unknown_prompt():
    with pytest.raises(FileNotFoundError):
        load_prompt("nope")
