from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["ltr", "rtl"]


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    direction: Direction
    stopwords: frozenset[str]
    # Single-letter clitics that attach to the front of Hebrew words (and, the, in, to, from, that, as).
    prefixes: tuple[str, ...] = ()


_HE_STOPWORDS = frozenset(
    "של את על עם הוא היא הם הן זה זאת אני אתה את אנחנו לא כן גם כי אם או אבל יש אין כל מה מי איך למה "
    "כאשר אשר היה היו יהיה להיות בין עד אל מן אחרי לפני כמו יותר פחות רק עוד כבר אז שם פה כאן".split()
)
_EN_STOPWORDS = frozenset(
    "a an the and or but if then of to in on at by for with from as is are was were be been being it its "
    "this that these those there here he she they them his her their we you i not no yes do does did have "
    "has had will would can could should may might which who whom what when where why how than so "
    "such".split()
)
_PT_STOPWORDS = frozenset(
    "a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre e ou mas se "
    "que quem qual quais como quando onde porque não sim é são foi foram ser está estão ele ela eles elas "
    "eu tu nós vós seu sua seus suas meu minha este esta isto esse essa isso aquele aquela aquilo há mais "
    "menos já".split()
)

LANGUAGES: dict[str, Language] = {
    "he": Language(
        code="he", name="Hebrew", direction="rtl", stopwords=_HE_STOPWORDS,
        prefixes=("ו", "ה", "ב", "ל", "מ", "ש", "כ"),
    ),
    "en": Language(code="en", name="English", direction="ltr", stopwords=_EN_STOPWORDS),
    "pt": Language(code="pt", name="Portuguese", direction="ltr", stopwords=_PT_STOPWORDS),
}


def get_language(code: str) -> Language:
    """KeyError for unsupported codes; callers validate at the boundary."""
    return LANGUAGES[code]
