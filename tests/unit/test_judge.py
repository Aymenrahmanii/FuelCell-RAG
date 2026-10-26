import json
from pathlib import Path

from fcrag.eval.judge import (
    agreement,
    claims,
    faithfulness,
    judge_run,
    parse_verdict,
    write_judgements,
)


def test_claims_keep_only_cited_sentences() -> None:
    answer = "The limit is 85 °C [S1][S2]. It is a stack. Version 1 said 90 °C [S3] [S1]."
    assert claims(answer) == [
        ("The limit is 85 °C .", [1, 2]),
        ("Version 1 said 90 °C  .", [3, 1]),
    ]


def test_parse_verdict_handles_reasoning_and_noise() -> None:
    assert parse_verdict('{"supported": true, "reason": "matches"}') == (True, "matches")
    thinking = '<think>{"supported": false}</think> Answer: {"supported": false, "reason": "x"}'
    assert parse_verdict(thinking) == (False, "x")
    assert parse_verdict("I think it is fine")[0] is None


def test_judge_run_and_scores(tmp_path: Path) -> None:
    run = {
        "results": [
            {"id": "q1", "answer": "A is 85 °C [S1]. B is 3 kW [S2].", "refused": False,
             "sources": [{"label": "S1", "title": "DS", "location": "p. 1", "text": "A: 85 °C"},
                         {"label": "S2", "title": "DS", "location": "p. 2", "text": "B: 4 kW"}]},
            {"id": "q2", "answer": "Not in the documents.", "refused": True, "sources": []},
        ]
    }  # fmt: skip
    prompts: list[str] = []

    def fake_judge(prompt: str) -> str:
        prompts.append(prompt)
        ok = "85 °C" in prompt
        return json.dumps({"supported": ok, "reason": "ok" if ok else "value differs"})

    judgements = judge_run(run, fake_judge)
    assert [(j.question_id, j.supported) for j in judgements] == [("q1", True), ("q1", False)]
    assert "[S2] DS, p. 2\nB: 4 kW" in prompts[1]
    assert faithfulness(judgements)["faithfulness"] == 0.5

    path = tmp_path / "j.jsonl"
    write_judgements(judgements, path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["human"], rows[1]["human"] = True, True  # the human disagrees on the second
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert agreement(path) == {
        "labelled": 2, "agreement": 0.5, "judge_too_lenient": 0, "judge_too_strict": 1,
    }  # fmt: skip
