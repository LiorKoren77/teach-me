from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

_ANSWER_PREVIEW = 48


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class AnswerOutcome(BaseModel):
    """One fixture answer as the learning loop actually handled it."""

    question: str
    answer: str
    expected_grade: str
    grade: str
    """The grade the service recorded, or "rejected" when the answer never reached the grader."""
    route: str | None
    accepted: bool
    agrees: bool
    route_agrees: bool | None

    def describe(self) -> str:
        preview = self.answer[:_ANSWER_PREVIEW].replace("\n", " ") or "(empty)"
        return (
            f"{'ok ' if self.agrees else 'BAD'} {self.expected_grade:>10} -> {self.grade:<10}"
            f" route={self.route or '-':<17} | {preview}"
        )


class FixtureReport(BaseModel):
    language: str
    subject: str
    subject_id: UUID
    outline_ok: bool
    parts: int
    sections: int
    grading_agreement: float
    route_agreement: float
    relevance_false_rejects: int
    """Answers the fixture calls genuine attempts that the relevance gate refused anyway - the
    one failure mode that costs a student their answer rather than only a grade."""
    cost_usd: float
    answers: list[AnswerOutcome]
    notes: list[str] = []

    def render(self) -> str:
        lines = [
            f"[{self.language}] outline {'ok' if self.outline_ok else 'OUT OF BOUNDS'}"
            f" ({_plural(self.parts, 'part')}, {_plural(self.sections, 'section')});"
            f" grading agreement {self.grading_agreement:.0%};"
            f" route agreement {self.route_agreement:.0%};"
            f" false rejects {self.relevance_false_rejects}; cost ${self.cost_usd:.4f}"
        ]
        lines += [f"    {answer.describe()}" for answer in self.answers]
        lines += [f"    note: {note}" for note in self.notes]
        return "\n".join(lines)


class EvalReport(BaseModel):
    fixtures: list[FixtureReport]

    def render(self) -> str:
        if not self.fixtures:
            return "no fixtures ran"
        mean = sum(f.grading_agreement for f in self.fixtures) / len(self.fixtures)
        return "\n".join(
            [f.render() for f in self.fixtures]
            + [
                f"total: {_plural(len(self.fixtures), 'fixture')};"
                f" mean grading agreement {mean:.0%};"
                f" cost ${sum(f.cost_usd for f in self.fixtures):.4f}"
            ]
        )
