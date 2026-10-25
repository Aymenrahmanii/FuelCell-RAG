"""German/English detection, used for documents (enrichment) and questions (answer language)."""

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _detector() -> Any:
    from lingua import Language, LanguageDetectorBuilder

    return LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.GERMAN).build()


def detect_language(text: str, default: str = "en") -> str:
    """Return ``"de"`` or ``"en"``. Short or ambiguous text falls back to ``default``."""
    sample = text[:5000].strip()
    if not sample:
        return default
    language = _detector().detect_language_of(sample)
    if language is None:
        return default
    return "de" if language.name == "GERMAN" else "en"
