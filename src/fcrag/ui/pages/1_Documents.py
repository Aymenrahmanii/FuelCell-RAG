"""Document explorer: ingestion status of every document version in the registry."""

import streamlit as st

from fcrag.ui import client

st.set_page_config(page_title="Documents · FuelCell-RAG", page_icon="📄", layout="wide")
st.title("Documents")

try:
    rows = client.documents()
except Exception as exc:
    st.error(f"API not reachable: {exc}")
    st.stop()

statuses: dict[str, int] = {}
for r in rows:
    statuses[r["status"]] = statuses.get(r["status"], 0) + 1
cols = st.columns(4)
cols[0].metric("Documents", len(rows))
cols[1].metric("Indexed", statuses.get("indexed", 0))
cols[2].metric("Chunks", sum(r["chunk_count"] or 0 for r in rows))
cols[3].metric("Failed / quarantined", statuses.get("failed", 0) + statuses.get("quarantined", 0))

status_filter = st.multiselect("Status", sorted(statuses), default=sorted(statuses))
st.dataframe(
    [r for r in rows if r["status"] in status_filter],
    column_order=[
        "doc_id", "doc_version", "status", "title", "doc_type", "system", "language",
        "element_count", "chunk_count", "duration_s", "attempts", "error", "licence", "updated_at",
    ],
    hide_index=True,
    use_container_width=True,
)  # fmt: skip
st.caption("Re-ingest with `uv run fcrag ingest` (only new or changed files are processed).")
