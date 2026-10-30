"""Follow-up questions: rewrite the last question of a conversation into a standalone one.

"And for System C?" retrieves nothing useful on its own. With the conversation, a small LLM call
turns it into "What is the maximum coolant outlet temperature of System C?", which retrieval and
the answer prompt then use. Any failure falls back to the question as asked: a chat must never
break because the rewrite did.
"""

import logging
import re
from typing import Literal, TypedDict

from fcrag.llm.client import LLM, Message

log = logging.getLogger(__name__)

MAX_TURNS = 6
"""Most recent turns given to the rewrite; older ones rarely hold the referent."""
MAX_TURN_CHARS = 800
"""Answers are long; their start names what was asked about."""
CITATION = re.compile(r"\s*\[S\d+\]")


class Turn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


def format_history(history: list[Turn]) -> str:
    lines = []
    for turn in history[-MAX_TURNS:]:
        text = CITATION.sub("", " ".join(turn["content"].split()))
        if len(text) > MAX_TURN_CHARS:
            text = text[:MAX_TURN_CHARS] + " …"
        lines.append(f"{'User' if turn['role'] == 'user' else 'Assistant'}: {text}")
    return "\n".join(lines)


def clean(output: str, question: str) -> str:
    """The rewritten question, or the original when the output is not a usable question."""
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    if not lines:
        return question
    text = lines[0].strip().strip("\"'„“”«»").strip()
    text = re.sub(r"^(?:standalone question|rewritten question|frage)\s*:\s*", "", text, flags=re.I)
    # An answer instead of a question, or a ramble: not worth retrieving with
    if not text or len(text) > max(300, 4 * len(question)):
        return question
    return text


def rewrite(llm: LLM, question: str, history: list[Turn], prompt: dict[str, str]) -> str:
    """Standalone version of ``question``; ``question`` itself without history or on failure."""
    if not history:
        return question
    messages: list[Message] = [
        {"role": "system", "content": prompt["system"]},
        {
            "role": "user",
            "content": prompt["user"].format(history=format_history(history), question=question),
        },
    ]
    try:
        return clean("".join(llm.stream(messages)), question)
    except Exception as exc:
        log.warning("follow-up rewrite failed, using the question as asked: %s", exc)
        return question
