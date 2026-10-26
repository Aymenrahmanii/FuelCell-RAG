"""LLM judge for faithfulness: is each cited sentence supported by the sources it cites?

The judge should be a different model family from the generator, so it does not grade its own
style. Its decisions are written to a JSONL file with an empty ``human`` field: label a sample
by hand and run ``fcrag judge-agreement`` before trusting the judged metrics.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fcrag.generation.citations import CITATION, SENTENCE_END

PROMPT = """You check an engineering answer against its sources.

Statement:
{statement}

Sources cited by the statement:
{sources}

Is every fact in the statement (numbers, units, conditions, names) supported by these sources?
Paraphrase and translation (English/German) are fine; a value or condition that is missing,
different or invented is not.
Reply with one line of JSON: {{"supported": true or false, "reason": "<at most 20 words>"}}"""

JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class Judgement:
    question_id: str
    statement: str
    cited: list[str]
    supported: bool | None
    """None when the judge's reply could not be parsed."""
    reason: str
    human: bool | None = None
    """Fill in by hand for calibration."""


def claims(answer: str) -> list[tuple[str, list[int]]]:
    """Sentences carrying at least one citation, with their source numbers."""
    out = []
    for sentence in SENTENCE_END.split(answer.strip()):
        numbers = [int(n) for n in CITATION.findall(sentence)]
        text = CITATION.sub("", sentence).strip()
        if numbers and len(text) > 3:
            out.append((text, list(dict.fromkeys(numbers))))
    return out


def parse_verdict(reply: str) -> tuple[bool | None, str]:
    match = JSON_OBJECT.search(THINK.sub("", reply))
    if not match:
        return None, reply.strip()[:200]
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, reply.strip()[:200]
    supported = data.get("supported")
    return (supported if isinstance(supported, bool) else None), str(data.get("reason", ""))


def litellm_judge(model: str) -> Callable[[str], str]:
    def ask(prompt: str) -> str:
        import litellm

        response: Any = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            num_retries=3,
            timeout=60,
        )
        return str(response.choices[0].message.content or "")

    return ask


def judge_run(
    run: dict[str, Any], ask: Callable[[str], str], *, pause_s: float = 0.0
) -> list[Judgement]:
    judgements = []
    for result in run["results"]:
        if not result.get("answer") or result.get("refused"):
            continue
        by_label = {s["label"]: s for s in result.get("sources", [])}
        for statement, numbers in claims(result["answer"]):
            cited = [by_label[f"S{n}"] for n in numbers if f"S{n}" in by_label]
            if not cited:
                continue  # invalid citations are counted separately by the runner
            sources = "\n\n".join(
                f"[{s['label']}] {s['title']}, {s['location']}\n{s['text']}" for s in cited
            )
            reply = ask(PROMPT.format(statement=statement, sources=sources))
            supported, reason = parse_verdict(reply)
            judgements.append(
                Judgement(result["id"], statement, [s["label"] for s in cited], supported, reason)
            )
            if pause_s:
                time.sleep(pause_s)
    return judgements


def faithfulness(judgements: list[Judgement]) -> dict[str, Any]:
    """Mean per-answer share of supported claims (unparsed verdicts excluded)."""
    per_answer: dict[str, list[bool]] = {}
    for j in judgements:
        if j.supported is not None:
            per_answer.setdefault(j.question_id, []).append(j.supported)
    scores = [sum(v) / len(v) for v in per_answer.values() if v]
    return {
        "faithfulness": sum(scores) / len(scores) if scores else None,
        "claims": len(judgements),
        "supported": sum(1 for j in judgements if j.supported),
        "unparsed": sum(1 for j in judgements if j.supported is None),
        "answers_judged": len(scores),
    }


def write_judgements(judgements: list[Judgement], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for j in judgements:
            f.write(json.dumps(asdict(j), ensure_ascii=False) + "\n")


def agreement(path: Path) -> dict[str, Any]:
    """Judge vs human labels, over the judgements a person has labelled."""
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    labelled = [r for r in rows if r.get("human") is not None and r.get("supported") is not None]
    agree = sum(r["human"] == r["supported"] for r in labelled)
    return {
        "labelled": len(labelled),
        "agreement": agree / len(labelled) if labelled else None,
        "judge_too_lenient": sum(r["supported"] and not r["human"] for r in labelled),
        "judge_too_strict": sum(r["human"] and not r["supported"] for r in labelled),
    }
