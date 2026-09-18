from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def load_prompt(name: str) -> str:
    """Prompt text from `<name>.md` next to this file. Raises FileNotFoundError for unknown names."""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
