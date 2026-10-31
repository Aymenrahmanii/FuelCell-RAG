"""Evaluation dashboard: saved runs, a comparison between two of them, and failing questions."""

from typing import Any

import streamlit as st

from fcrag.ui import client

st.set_page_config(page_title="Evaluation · FuelCell-RAG", page_icon="📊", layout="wide")
st.title("Evaluation")
st.caption("Runs saved by `fcrag eval` in eval/runs. Retrieval metrics always; answer metrics "
           "for runs made with --answers.")  # fmt: skip

METRICS = [
    ("recall@5", "Recall@5", True), ("mrr", "MRR", True), ("ndcg@10", "nDCG@10", True),
    ("value_accuracy", "Value accuracy", True), ("citation_precision", "Citation precision", True),
    ("faithfulness", "Faithfulness", True), ("false_refusal", "False refusals", False),
    ("retrieval_p95_s", "Retrieval p95 (s)", False),
]  # fmt: skip
"""Key, label, and whether higher is better (for the colour of the change)."""

try:
    runs = client.eval_runs()
except Exception as exc:
    st.error(f"API not reachable: {exc}")
    st.stop()
if not runs:
    st.info("No runs yet. Run `uv run fcrag eval` (add `--answers` for answer metrics).")
    st.stop()

st.dataframe(
    [{k: v for k, v in r.items() if k not in {"config", "injection"}} for r in runs],
    hide_index=True,
    use_container_width=True,
)

names = [r["name"] for r in runs]
left, right = st.columns(2)
current = left.selectbox("Run", names, index=0)
baseline = right.selectbox("Compare with", ["(none)", *names], index=min(2, len(names)))
by_name = {r["name"]: r for r in runs}
run, base = by_name[current], by_name.get(baseline)


def fmt(value: Any) -> str:
    return "–" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


cols = st.columns(len(METRICS))
for col, (key, label, higher_better) in zip(cols, METRICS, strict=True):
    value = run.get(key)
    delta = None
    if base is not None and value is not None and base.get(key) is not None:
        delta = round(value - base[key], 3)
    col.metric(label, fmt(value), delta, delta_color="normal" if higher_better else "inverse")

if base is not None:
    changed = {
        k: (base["config"].get(k), v) for k, v in run["config"].items()
        if base["config"].get(k) != v
    }  # fmt: skip
    if changed:
        st.caption("Configuration changes: " + "; ".join(
            f"{k}: {old} → {new}" for k, (old, new) in changed.items()))  # fmt: skip

detail = client.eval_run(current)
st.subheader("Recall@5 per category")
st.dataframe(
    [{"category": c, **v} for c, v in detail["summary"].get("by_category", {}).items()],
    hide_index=True,
)
if run.get("injection"):
    inj = run["injection"]
    st.caption(f"Prompt injection: {inj['resisted']} of {inj['questions']} answers resisted; the "
               f"planted note was among the sources in {inj['planted_in_sources']}.")  # fmt: skip


def problems(r: dict[str, Any]) -> list[str]:
    """Why a question counts as failing; empty when it passed everything measured."""
    issues = []
    if r.get("error"):
        issues.append("error")
    if r.get("answerable") and r.get("category") != "unanswerable":
        if r.get("rank") is None:
            issues.append("no gold source retrieved")
        elif r["rank"] > 5:
            issues.append(f"gold source at rank {r['rank']}")
        if r.get("refused"):
            issues.append("refused")
    elif r.get("refused") is False:
        issues.append("answered an unanswerable question")
    if r.get("values_ok") is False:
        issues.append("wrong or missing value")
    if r.get("terms_ok") is False:
        issues.append("missing ID or term")
    if r.get("resisted") is False:
        issues.append("followed a planted instruction")
    return issues


failing = [
    {"id": r["id"], "category": r["category"], "question": r.get("question", ""),
     "issues": ", ".join(p), "rank": r.get("rank"), "top sources": ", ".join(r.get("top", [])[:3])}
    for r in detail.get("results", []) if (p := problems(r))
]  # fmt: skip
st.subheader(f"Failing questions ({len(failing)} of {len(detail.get('results', []))})")
if failing:
    st.dataframe(failing, hide_index=True, use_container_width=True)
else:
    st.success("Every question passed what this run measured.")

with st.expander("Answers"):
    for r in detail.get("results", []):
        if r.get("answer"):
            st.markdown(f"**{r['id']}** · {r.get('question', '')}\n\n{r['answer']}")
