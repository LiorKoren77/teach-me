from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from teachme.generation.errors import GenerationValidationError
from teachme.ports.llm import ContentPart, LLMProvider, StructuredRequest, StructuredResult, T

Validator = Callable[[T], list[str]]


def generate_validated(
    llm: LLMProvider, request: StructuredRequest, schema: type[T], *, validate: Validator
) -> StructuredResult[T]:
    """Call once; if the validator returns errors, call once more with the errors appended to the
    user message; if it still fails, raise. Generated output is never trusted without this."""
    result = llm.generate_structured(request, schema)
    errors = validate(result.output)
    if not errors:
        return result
    feedback = (
        "\n\nPrevious attempt failed validation. Fix every problem below and return the complete output "
        "again:\n- " + "\n- ".join(errors)
    )
    retry = replace(request, parts=(*request.parts, ContentPart.of_text(feedback)))
    result = llm.generate_structured(retry, schema)
    errors = validate(result.output)
    if errors:
        raise GenerationValidationError(request.purpose, errors)
    return result
