from __future__ import annotations


class GenerationError(Exception):
    pass


class GenerationValidationError(GenerationError):
    def __init__(self, purpose: str, errors: list[str]) -> None:
        super().__init__(f"{purpose}: output failed validation twice: {errors}")
        self.errors = errors


class SubjectNotReady(GenerationError):
    pass


class CorpusTooLarge(GenerationError):
    pass
