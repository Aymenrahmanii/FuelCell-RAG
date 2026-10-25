"""Requirement checker: similar and linked requirements, and conflicting values (FR-10, FR-11)."""

import streamlit as st

from fcrag.ui import client

SYSTEMS = ["(detect from text)", "System A", "System B", "System C"]
EXAMPLE = "The fuel cell stack shall not exceed a maximum coolant outlet temperature of 90 °C."
ICONS = {"conflict": "🔴", "consistent": "🟢", "unknown": "⚪"}

st.set_page_config(page_title="Requirement checker · FuelCell-RAG", page_icon="✅", layout="wide")
st.title("Requirement checker")
st.caption("Paste a draft requirement. Values are checked against the current documents.")

text = st.text_area("Requirement", value=EXAMPLE, height=110)
choice = st.selectbox("System", SYSTEMS, index=1)
if not st.button("Check", type="primary"):
    st.stop()

try:
    result = client.check_requirement(text, None if choice == SYSTEMS[0] else choice)
except Exception as exc:
    st.error(f"Check failed: {exc}")
    st.stop()

if result["system"] is None:
    st.warning("No system found. Name one in the text or pick it above.")
    st.stop()

st.subheader(f"Values ({result['system']})")
if not result["parameters"]:
    st.info("No known parameter with a value was found in the text.")
for check in result["parameters"]:
    st.markdown(
        f"{ICONS[check['status']]} **{check['label']}** {check['component'] or ''}: "
        f"draft states **{check['stated']}** → {check['status']}"
    )
    for doc in check["documents"]:
        mark = "✓" if doc["agrees"] else "✗"
        st.markdown(
            f"&nbsp;&nbsp;&nbsp;{mark} {doc['title']} v{doc['doc_version']}, {doc['location']}: "
            f"{doc['value']:g} {check['unit_norm']}"
        )

st.subheader("Similar requirements")
for req in result["similar"]:
    with st.expander(f"{req['req_id']} · score {req['score']:.2f} · {req['status'] or ''}"):
        st.text(req["text"])
if result["linked"]:
    st.subheader("Linked requirements")
    st.write(", ".join(result["linked"]))
