"""Deterministic stand-ins for models, so pipeline and service tests need no GPU or network."""

import hashlib
import math
import re
from collections.abc import Iterator
from pathlib import Path

from fcrag.embedding import Embedding
from fcrag.llm.client import Message
from fcrag.models import Element, SourceFile

WORD = re.compile(r"\w+")


def _bucket(token: str, size: int) -> int:
    return int(hashlib.md5(token.encode()).hexdigest(), 16) % size


class FakeEmbedder:
    """Hashed bag of words: texts sharing words get similar vectors."""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str], *, max_tokens: int | None = None) -> list[Embedding]:
        self.calls += 1
        out = []
        for text in texts:
            tokens = [t.lower() for t in WORD.findall(text)]
            dense = [0.0] * 1024
            sparse: dict[int, float] = {}
            for t in tokens:
                dense[_bucket(t, 1024)] += 1.0
                key = _bucket(t, 50_000)
                sparse[key] = sparse.get(key, 0.0) + 1.0
            norm = math.sqrt(sum(v * v for v in dense)) or 1.0
            out.append(Embedding([v / norm for v in dense], sparse))
        return out


class OverlapReranker:
    """Score = share of query words found in the text."""

    def score(self, query: str, texts: list[str]) -> list[float]:
        q = {t.lower() for t in WORD.findall(query)}
        return [len(q & {t.lower() for t in WORD.findall(text)}) / max(len(q), 1) for text in texts]


class ScriptedLLM:
    model = "fake/scripted"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.messages: list[Message] = []

    def stream(self, messages: list[Message]) -> Iterator[str]:
        self.messages = messages
        yield from self.answer.split(" ")[:1]
        for word in self.answer.split(" ")[1:]:
            yield " " + word


class LineParser:
    """Parses .txt fixtures: '# ' lines are headings, '!fail' raises, other lines are text."""

    supported_types = frozenset({".txt"})

    def parse(self, file: SourceFile) -> Iterator[Element]:
        heading: list[str] = []
        for n, line in enumerate(Path(file.path).read_text(encoding="utf-8").splitlines(), 1):
            if line == "!fail":
                raise ValueError("corrupt file")
            if line.startswith("# "):
                heading = [line[2:]]
            elif line.strip():
                yield Element(kind="text", content=line, heading_path=heading, locator={"page": n})
