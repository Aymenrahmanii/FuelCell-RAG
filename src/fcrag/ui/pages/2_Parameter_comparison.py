"""Parameter comparison across systems, straight from the parameters table (FR-09, FR-11)."""

from typing import Any

import streamlit as st

from fcrag.ui import client

SYSTEMS = ["System A", "System B", "System C"]
DEFAULT_KEYS = ["rated_net_power", "coolant_outlet_temperature_max", "membrane_thickness",
                "pt_loading_cathode", "design_lifetime"]  # fmt: skip

st.set_page_config(page_title="Compare · FuelCell-RAG", page_icon="📊", layout="wide")
st.title("Parameter comparison")
st.caption(
    "Values come from the extracted parameters table, normalised to one unit per parameter. "
    "⚠️ marks a parameter whose current documents disagree."
)

try:
    keys = client.parameter_keys()
except Exception as exc:
    st.error(f"API not reachable: {exc}")
    st.stop()
labels = {k["key"]: k["label_en"] for k in keys}
systems = st.multiselect("Systems", SYSTEMS, default=SYSTEMS)
chosen = st.multiselect(
    "Parameters", list(labels), default=[k for k in DEFAULT_KEYS if k in labels],
    format_func=lambda k: labels[k],
)  # fmt: skip
if not (systems and chosen):
    st.stop()

table = client.compare(systems, chosen)


def cell_text(cell: dict[str, Any]) -> str:
    if cell["value"] is None:
        return "–"
    value = f"{cell['value']:g} {cell['unit']}".replace(" –", "").strip()
    return value if cell["agree"] else f"⚠️ {value}"


st.dataframe(
    [{"Parameter": labels[k], **{s: cell_text(table[k][s]) for s in systems}} for k in chosen],
    hide_index=True,
    use_container_width=True,
)

st.subheader("Sources")
for key in chosen:
    with st.expander(labels[key]):
        for system in systems:
            for src in table[key][system]["sources"]:
                version = f"v{src['doc_version']}" + ("" if src["is_latest"] else ", superseded")
                where = f"{src['title']} ({version}) · {src['location']}"
                st.markdown(f"**{system}** · {src['stated']} · {where}")
