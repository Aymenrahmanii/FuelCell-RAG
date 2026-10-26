"""Source labels, locator formatting and citation checks."""

import re
from dataclasses import dataclass, field
from typing import Any

CITATION = re.compile(r"\[S(\d+)\]")
# Some models (gpt-oss) write full-width brackets, sometimes with line spans: 【S1】, 【S2†L1-L3】
VARIANT_CITATION = re.compile(r"[【［\[]\s*S\s*(\d+)(?:†[^】］\]]*)?\s*[】］\]]")
# Non-breaking hyphens and spaces that models emit; IDs such as REQ-A-0001 must stay searchable
TYPOGRAPHY = str.maketrans({"\u2010": "-", "\u2011": "-", "\u00a0": " ", "\u202f": " "})


def normalise_citations(answer: str) -> str:
    """Rewrite citation variants as [S1] and typographic hyphens/spaces as ASCII, so checks,
    display and copying see one format."""
    return VARIANT_CITATION.sub(lambda m: f"[S{m.group(1)}]", answer.translate(TYPOGRAPHY))


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9])")


def format_locator(locator: dict[str, Any]) -> str:
    """Human-readable position: page, sheet and cells, requirement ID or CAD part."""
    parts = []
    if "pages" in locator:
        parts.append(f"pp. {locator['pages'][0]}-{locator['pages'][-1]}")
    elif "page" in locator:
        parts.append(f"p. {locator['page']}")
    if "sheet" in locator:
        cells = f"!{locator['cells']}" if "cells" in locator else ""
        parts.append(f"sheet {locator['sheet']}{cells}")
    if "row" in locator:
        parts.append(f"table row {locator['row']}")
    if "req_id" in locator:
        parts.append(str(locator["req_id"]))
    if "part_id" in locator:
        parts.append(f"part {locator['part_id']}")
    return ", ".join(parts)


@dataclass
class CitationReport:
    cited: list[int] = field(default_factory=list)
    """Source numbers cited, in order of first use."""
    invalid: list[int] = field(default_factory=list)
    """Cited numbers with no matching source; the model invented them."""
    uncited_sentences: list[str] = field(default_factory=list)
    """Sentences containing a digit but no citation: likely unsupported facts."""

    @property
    def ok(self) -> bool:
        return not self.invalid


def check_citations(answer: str, n_sources: int) -> CitationReport:
    answer = normalise_citations(answer)
    report = CitationReport()
    for match in CITATION.finditer(answer):
        n = int(match.group(1))
        target = report.cited if 1 <= n <= n_sources else report.invalid
        if n not in target:
            target.append(n)
    for sentence in SENTENCE_END.split(answer.strip()):
        if any(ch.isdigit() for ch in CITATION.sub("", sentence)) and not CITATION.search(sentence):
            report.uncited_sentences.append(sentence.strip())
    return report
