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
             "sources": [{"label": "S1", "title": "DS", "doc_version": 2, "is_latest": True,
                          "location": "p. 1", "text": "A: 85 °C"},
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
    assert "[S1] DS, v2 (latest), p. 1\nA: 85 °C" in prompts[0]
    assert "[S2] DS, p. 2\nB: 4 kW" in prompts[1]
    assert faithfulness(judgements)["faithfulness"] == 0.5

    path = tmp_path / "j.jsonl"
    write_judgements(judgements, path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["human"], rows[1]["human"] = True, True  # the human disagrees on the second
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert agreement(path) == {
        "labeller": "human", "labelled": 2, "agreement": 0.5,
        "judge_too_lenient": 0, "judge_too_strict": 1,
    }  # fmt: skip


def test_interactive_labelling_hides_verdict_and_resumes(tmp_path: Path) -> None:
    from fcrag.eval.judge import label_interactively

    rows = [
        {"question_id": "q1", "statement": "A is 85 °C.", "cited": ["S1"], "supported": True,
         "reason": "SECRET-REASON", "human": None},
        {"question_id": "q1", "statement": "B is 3 kW.", "cited": ["S2"], "supported": False,
         "reason": "SECRET-REASON", "human": None},
    ]  # fmt: skip
    path = tmp_path / "j.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    run = {"results": [{"id": "q1", "sources": [
        {"label": "S1", "title": "DS", "location": "p. 1", "text": "A: 85 °C"},
        {"label": "S2", "title": "DS", "location": "p. 2", "text": "B: 4 kW"}]}]}  # fmt: skip
    shown: list[str] = []
    replies = iter(["maybe", "y", "q"])  # invalid input is asked again; q stops the session

    done = label_interactively(path, run, ask=lambda _: next(replies), show=shown.append)

    text = "\n".join(shown)
    assert done == 1
    assert "SECRET-REASON" not in text
    assert "A: 85 °C" in text or "B: 4 kW" in text
    saved = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert sum(r["human"] is not None for r in saved) == 1
    # a second session only asks about the remaining claim
    again = label_interactively(path, run, ask=lambda _: "n", show=lambda _: None)
    assert again == 1
    assert all(
        json.loads(line)["human"] is not None for line in path.read_text("utf-8").splitlines()
    )


def test_agreement_with_a_named_labeller(tmp_path: Path) -> None:
    rows = [
        {"supported": True, "claude": True, "human": None},
        {"supported": True, "claude": False, "human": None},
        {"supported": False, "claude": False, "human": None},
    ]
    path = tmp_path / "j.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    result = agreement(path, "claude")
    assert result["labeller"] == "claude" and result["labelled"] == 3
    assert result["judge_too_lenient"] == 1 and round(result["agreement"], 3) == 0.667
    assert agreement(path)["labelled"] == 0  # no human labels yet
