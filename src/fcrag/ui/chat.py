"""Chat page. Run with: uv run streamlit run src/fcrag/ui/chat.py"""

from typing import Any

import streamlit as st

from fcrag.ui import client

SYSTEMS = ["System A", "System B", "System C"]
DOC_TYPES = ["report", "datasheet", "parameter_sheet", "requirements", "drawing", "cad"]

st.set_page_config(page_title="FuelCell-RAG", page_icon="⚡", layout="wide")


def sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.header("Filters")
        systems = st.multiselect("Fuel cell system", SYSTEMS)
        doc_types = st.multiselect("Document type", DOC_TYPES)
        latest_only = st.toggle("Latest document versions only", value=False)
        st.divider()
        status = client.health()
        ok = status.get("status") == "ok"
        st.caption(f"API: {'🟢' if ok else '🔴'} {status.get('status')}")
        if st.button("Clear chat"):
            st.session_state.messages = []
            st.rerun()
    return {"systems": systems, "doc_types": doc_types, "latest_only": latest_only}


def plain_text(answer: str, sources: list[dict[str, Any]]) -> str:
    """Answer plus its sources, for copying into a report or email."""
    lines = [answer, "", "Sources:"]
    for s in sources:
        where = f", {s['location']}" if s["location"] else ""
        lines.append(f"[{s['label']}] {s['title']} (v{s['doc_version']}{where})")
    return "\n".join(lines)


def show_sources(sources: list[dict[str, Any]], cited: list[int], key: str) -> None:
    if not sources:
        return
    st.markdown("**Sources**")
    for n, s in enumerate(sources, 1):
        mark = "✅" if n in cited else "·"
        version = f"v{s['doc_version']}" + ("" if s["is_latest"] else ", superseded")
        where = f" · {s['location']}" if s["location"] else ""
        label = f"{mark} [{s['label']}] {s['title']} ({version}){where} · score {s['score']:.2f}"
        with st.expander(label):
            st.markdown(s["text"])
            page = s["locator"].get("page")
            if page and st.button("Show page", key=f"{key}-page-{n}"):
                image = client.page_image(s["doc_id"], s["doc_version"], page)
                if image:
                    st.image(image, caption=f"{s['title']}, page {page}")
                else:
                    st.info("No page preview for this source.")


def show_feedback(message: dict[str, Any], key: str) -> None:
    result = message.get("result") or {}
    if not result or message.get("feedback_sent"):
        return
    cols = st.columns([1, 1, 8])
    rating = (
        1
        if cols[0].button("👍", key=f"{key}-up")
        else -1
        if cols[1].button("👎", key=f"{key}-down")
        else 0
    )
    comment = cols[2].text_input(
        "Comment",
        key=f"{key}-comment",
        label_visibility="collapsed",
        placeholder="Comment (optional), then rate",
    )
    if rating:
        sent = client.send_feedback(
            {
                "question": result["question"],
                "answer": result["answer"],
                "rating": rating,
                "comment": comment or None,
                "sources": [
                    {k: s[k] for k in ("doc_id", "doc_version", "locator", "score")}
                    for s in result["sources"]
                ],
                "model": result.get("model"),
                "prompt_version": result.get("prompt_version"),
                "trace_id": result.get("trace_id"),
            }
        )
        message["feedback_sent"] = sent
        st.toast("Thanks, feedback saved." if sent else "Could not save feedback.")


def render(message: dict[str, Any], key: str) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        result = message.get("result")
        if not result:
            return
        if result.get("invalid_citations"):
            st.warning(f"The model cited sources that do not exist: {result['invalid_citations']}")
        searched = result.get("search_question")
        if searched and searched != result["question"]:
            st.caption(f"Searched as: {searched}")
        if not result["found"]:
            st.info("No reliable source found.")
        show_sources(result["sources"], result["cited"], key)
        if result["sources"]:
            with st.expander("Copy answer with citations"):
                st.code(plain_text(result["answer"], result["sources"]), language=None)
        t = result["timings"]
        st.caption(
            f"retrieval {t['embed_s'] + t['search_s'] + t['rerank_s']:.1f}s · "
            f"generation {t['generate_s']:.1f}s · {result.get('model') or 'no LLM call'}"
        )
        show_feedback(message, key)


def main() -> None:
    filters = sidebar()
    st.title("FuelCell-RAG")
    st.caption("Answers from fuel cell engineering documents. Every claim cites its source.")
    messages: list[dict[str, Any]] = st.session_state.setdefault("messages", [])
    for i, message in enumerate(messages):
        render(message, f"m{i}")

    question = st.chat_input("Ask about stacks, limits, requirements… (English or Deutsch)")
    if not question:
        return
    # Earlier turns let the API resolve follow-ups ("and for System C?"); errors are left out
    history = [{"role": m["role"], "content": m["content"]} for m in messages
               if m["role"] == "user" or m.get("result")]  # fmt: skip
    messages.append({"role": "user", "content": question})
    render(messages[-1], f"m{len(messages) - 1}")

    with st.chat_message("assistant"):
        state: dict[str, Any] = {}

        def tokens() -> Any:
            for event in client.ask_stream({"question": question, "history": history, **filters}):
                if event["type"] == "token":
                    yield event["text"]
                elif event["type"] == "done":
                    state["result"] = event["result"]
                elif event["type"] == "error":
                    state["error"] = event["message"]

        try:
            text = st.write_stream(tokens())
        except Exception as exc:
            text, state["error"] = "", str(exc)
    if "error" in state:
        st.error(state["error"])
        messages.append({"role": "assistant", "content": f"⚠️ {state['error']}"})
    else:
        result = state.get("result")
        # Show the stored answer: citations are normalised there ([S1] instead of 【S1】)
        content = result["answer"] if result else str(text)
        messages.append({"role": "assistant", "content": content, "result": result})
    st.rerun()


main()
