from __future__ import annotations

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "rejected": "That does not answer the question. Try again.",
        "rejected_final": "That does not answer the question. Moving on.",
        "mc_correct": "Correct.",
        "mc_incorrect": "Not this one.",
    },
    "he": {
        "rejected": "זו אינה תשובה לשאלה. נסו שוב.",
        "rejected_final": "זו אינה תשובה לשאלה. ממשיכים.",
        "mc_correct": "נכון.",
        "mc_incorrect": "לא זו.",
    },
    "pt": {
        "rejected": "Isso não responde à pergunta. Tente de novo.",
        "rejected_final": "Isso não responde à pergunta. Vamos continuar.",
        "mc_correct": "Correto.",
        "mc_incorrect": "Não é esta.",
    },
}


def message(language: str, key: str) -> str:
    """Fixed student-facing strings. Never model-generated, so they cost nothing and never drift."""
    return _MESSAGES.get(language, _MESSAGES["en"])[key]
