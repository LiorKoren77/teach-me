from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SOURCE_GLOB = "source*.md"
"""A fixture's material, one or more markdown files, sorted by filename: several files ingest as
several one-page sources, which is what gives a text fixture more than one page to outline."""
SPEC_NAMES = ("expected.json", "expected.yaml", "expected.yml")

ExpectedGrade = Literal["correct", "partial", "incorrect", "off_topic", "junk"]


class FixtureError(Exception):
    """A fixture folder this harness cannot run: no spec, no source, or a spec it cannot read."""


class ExpectedAnswer(BaseModel):
    """One synthetic student answer and what the material says should become of it.

    `question_contains` is a case-insensitive substring used to pick which of the round's
    free-text questions to answer; empty means any of them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_contains: str = ""
    answer: str
    expected_grade: ExpectedGrade
    expected_route: str | None = None


class OutlineBounds(BaseModel):
    """What a sane outline of this source looks like. Bounds rather than an exact shape: two
    models will split the same text differently without either being wrong."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_parts: int = Field(ge=1)
    max_parts: int = Field(ge=1)
    min_sections: int = Field(ge=1)


class Fixture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    language: str = Field(min_length=2, max_length=2, description="The language the source is written in")
    teach_in: list[str] = Field(
        min_length=1, description="Languages to generate; the first is the one answered in"
    )
    outline: OutlineBounds
    answers: list[ExpectedAnswer] = Field(min_length=1)


class FixtureCase(BaseModel):
    """A fixture folder: the source to ingest and the expectations to score against."""

    model_config = ConfigDict(frozen=True)

    folder: Path
    spec: Fixture

    @property
    def sources(self) -> list[tuple[str, bytes]]:
        """Every source file for this fixture, by filename, in sorted (reading) order."""
        return [(path.name, path.read_bytes()) for path in sorted(self.folder.glob(SOURCE_GLOB))]


def load_cases(directory: Path | None = None, *, languages: Sequence[str] | None = None) -> list[FixtureCase]:
    """Every fixture folder under `directory` (the shipped ones by default), in folder order."""
    root = Path(directory) if directory is not None else FIXTURES_DIR
    if not root.is_dir():
        raise FixtureError(f"no fixture directory at {root}")
    wanted = set(languages or ())
    cases = list(_load(folder) for folder in sorted(_folders(root)))
    cases = [case for case in cases if not wanted or case.spec.language in wanted]
    if not cases:
        raise FixtureError(f"no fixture in {root} for {sorted(wanted) if wanted else 'any language'}")
    return cases


def _folders(root: Path) -> list[Path]:
    return [path for path in root.iterdir() if path.is_dir() and not path.name.startswith((".", "_"))]


def _load(folder: Path) -> FixtureCase:
    spec_path = next((folder / name for name in SPEC_NAMES if (folder / name).is_file()), None)
    if spec_path is None:
        raise FixtureError(f"{folder} has none of {', '.join(SPEC_NAMES)}")
    if not any(folder.glob(SOURCE_GLOB)):
        raise FixtureError(f"{folder} has no files matching {SOURCE_GLOB}")
    try:
        spec = Fixture.model_validate(_parse(spec_path))
    except ValueError as exc:
        raise FixtureError(f"{spec_path}: {exc}") from exc
    if spec.language != folder.name:
        raise FixtureError(
            f"{spec_path}: language {spec.language!r} does not match its folder name {folder.name!r}"
        )
    return FixtureCase(folder=folder, spec=spec)


def _parse(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - PyYAML is present in every env we ship
        raise FixtureError(f"{path}: reading a YAML fixture needs PyYAML installed") from exc
    return yaml.safe_load(text)
