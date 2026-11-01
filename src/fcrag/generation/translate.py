"""Cross-lingual retrieval: an English version of a German question.

Most documents are English, bge-m3 matches across languages only roughly, and the sparse half of
the hybrid search cannot match across languages at all. Retrieval therefore also searches with an
English translation of a German question. The answer is still written for the original question.
Any failure falls back to no translation: retrieval then works as before.
"""

import logging

from fcrag.generation.rewrite import clean
from fcrag.llm.client import LLM, Message

log = logging.getLogger(__name__)


def translate_query(llm: LLM, question: str, prompt: dict[str, str]) -> str | None:
    """English version of ``question``; None when the call fails or yields nothing new."""
    messages: list[Message] = [
        {"role": "system", "content": prompt["system"]},
        {"role": "user", "content": prompt["user"].format(question=question)},
    ]
    try:
        text = clean("".join(llm.stream(messages)), question)
    except Exception as exc:
        log.warning("query translation failed, searching with the question as asked: %s", exc)
        return None
    return text if text != question else None
