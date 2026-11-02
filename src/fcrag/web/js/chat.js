// Chat: streamed answers with item balloons, a numbered source register, and a title block.

import { api } from "./api.js";
import { append, clear, fmtS, h, icon, renderMarkdown, revision } from "./dom.js";

const SYSTEMS = ["System A", "System B", "System C"];
const DOC_TYPES = [
  ["report", "Report"],
  ["datasheet", "Datasheet"],
  ["parameter_sheet", "Parameter sheet"],
  ["requirements", "Requirements"],
  ["drawing", "Drawing"],
  ["cad", "CAD / STEP"],
];
// Each of these was answered correctly, with citations, in the saved evaluation runs.
const EXAMPLES = [
  ["EN", "What is the maximum air mass flow of the System A air compressor?"],
  ["DE", "Welche Auslegungslebensdauer gilt aktuell für System B?"],
  ["EN", "Which requirements refine REQ-A-0001?"],
];

// Kept while the user visits other screens
const state = {
  messages: [],
  scope: { systems: [], docTypes: [], latestOnly: false },
  selected: null,
  controller: null,
  corpus: null,
  draft: "",
  registerOpen: true,
};

export function mount({ main, tools }) {
  const busy = () => state.controller !== null;
  const thread = h("div", { class: "thread" });
  const registerHost = h("div");
  const root = h("div", { class: "chat" }, thread, registerHost);
  clear(main).append(root);

  const clearBtn = h(
    "button",
    {
      class: "btn small",
      type: "button",
      onclick: () => {
        if (busy()) state.controller.abort();
        state.messages = [];
        state.selected = null;
        draw();
      },
    },
    icon("trash", 16),
    "Clear chat",
  );
  tools.append(clearBtn);

  if (!state.corpus) {
    api
      .documents()
      .then((rows) => {
        state.corpus = {
          documents: rows.length,
          chunks: rows.reduce((sum, r) => sum + (r.chunk_count || 0), 0),
        };
        if (!state.messages.length) draw();
      })
      .catch(() => {});
  }

  // ----- Scope (running head) -----

  function scopeSheet() {
    const toggle = (list, value) => {
      const at = list.indexOf(value);
      if (at >= 0) list.splice(at, 1);
      else list.push(value);
      draw();
    };
    const chip = (label, active, onclick) =>
      h("button", { class: "chip", type: "button", "aria-pressed": String(active), onclick }, label);

    const compact = window.matchMedia("(max-width: 860px)").matches;
    const summary = [
      state.scope.systems.length ? state.scope.systems.join(", ") : "all systems",
      state.scope.docTypes.length ? `${state.scope.docTypes.length} document types` : "all document types",
      state.scope.latestOnly ? "latest versions" : "all versions",
    ].join(" · ");
    const wrap = (inner) =>
      compact
        ? h("details", { class: "sheet scope-details" }, h("summary", null, h("span", { class: "label" }, "Scope"), " ", summary), inner)
        : inner;
    return wrap(h(
      "section",
      { class: `${compact ? "" : "sheet "}scope`, "aria-label": "Search scope" },
      h(
        "div",
        { class: "group" },
        h("span", { class: "label" }, "System"),
        h(
          "div",
          { class: "chips" },
          SYSTEMS.map((s) => chip(s, state.scope.systems.includes(s), () => toggle(state.scope.systems, s))),
        ),
      ),
      h(
        "div",
        { class: "group" },
        h("span", { class: "label" }, "Document type"),
        h(
          "div",
          { class: "chips" },
          DOC_TYPES.map(([value, label]) =>
            chip(label, state.scope.docTypes.includes(value), () => toggle(state.scope.docTypes, value)),
          ),
        ),
      ),
      h(
        "div",
        { class: "group" },
        h("span", { class: "label" }, "Versions"),
        h(
          "label",
          { class: "check" },
          h("input", {
            type: "checkbox",
            checked: state.scope.latestOnly,
            onchange: (e) => {
              state.scope.latestOnly = e.target.checked;
              draw();
            },
          }),
          "Latest only",
        ),
      ),
    ));
  }

  // ----- Balloons <-> register -----

  function light(numbers, scroll) {
    for (const el of root.querySelectorAll("[data-on]")) el.removeAttribute("data-on");
    if (!numbers.length) return;
    const wanted = new Set(numbers.map(String));
    for (const b of thread.querySelectorAll(".bln[data-ns]")) {
      if (b.dataset.ns.split(",").some((n) => wanted.has(n))) b.setAttribute("data-on", "");
    }
    let first = true;
    for (const n of wanted) {
      const row = registerHost.querySelector(`.part[data-n="${n}"]`);
      if (!row) continue;
      row.setAttribute("data-on", wanted.size > 2 ? "together" : "");
      if (scroll && first) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
      first = false;
    }
  }

  function onBalloon(numbers, hover) {
    if (!hover) {
      const row = registerHost.querySelector(`.part[data-n="${numbers[0]}"] .part-row`);
      if (row && row.getAttribute("aria-expanded") !== "true") row.click();
    }
    light(numbers, !hover);
  }

  // ----- Answer -----

  function citedSet(msg) {
    return msg.result ? new Set(msg.result.cited) : null;
  }

  function copyText(msg) {
    const lines = [msg.text, "", "Sources:"];
    for (const [i, s] of (msg.result?.sources || msg.sources).entries()) {
      const where = s.location ? `, ${s.location}` : "";
      lines.push(`[S${i + 1}] ${s.title} (v${s.doc_version}${where})`);
    }
    return lines.join("\n");
  }

  function titleBlock(msg) {
    const r = msg.result;
    if (!r) return null;
    const t = r.timings || {};
    const retrieval = (t.embed_s || 0) + (t.search_s || 0) + (t.rerank_s || 0);
    const cell = (label, value, data) =>
      h("div", { class: "cell" }, h("dt", null, label), h("dd", { class: data ? "data" : "" }, value));
    return h(
      "dl",
      { class: "cells", style: "margin:0" },
      cell("Retrieval", fmtS(retrieval)),
      cell("Generation", r.model ? fmtS(t.generate_s) : "no model call"),
      cell("Model", r.model || "–", true),
      cell("Prompt", [r.prompt_version || "–", r.cached ? " · cached" : ""].join(""), true),
    );
  }

  function feedbackRow(msg) {
    const r = msg.result;
    if (!r) return null;
    const comment = h("input", { class: "input", type: "text", placeholder: "Comment (optional)", "aria-label": "Comment" });
    const saved = h("span", { class: "saved", role: "status" });
    const send = async (rating) => {
      try {
        await api.feedback({
          question: r.question,
          answer: r.answer,
          rating,
          comment: comment.value.trim() || null,
          sources: r.sources.map((s) => ({ doc_id: s.doc_id, doc_version: s.doc_version, locator: s.locator, score: s.score })),
          model: r.model,
          prompt_version: r.prompt_version,
          trace_id: r.trace_id,
        });
        msg.feedback = true;
        draw();
      } catch (error) {
        saved.textContent = `Could not save: ${error.message}`;
        saved.style.color = "var(--red)";
      }
    };
    const copy = h("button", { class: "btn small", type: "button" }, icon("copy", 16), "Copy with citations");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(copyText(msg));
        copy.lastChild.textContent = "Copied";
        setTimeout(() => (copy.lastChild.textContent = "Copy with citations"), 1600);
      } catch {
        copy.lastChild.textContent = "Copy failed";
      }
    });
    return h(
      "div",
      { class: "actions" },
      copy,
      h("span", { class: "spacer" }),
      msg.feedback
        ? h("span", { class: "saved" }, "Feedback saved")
        : [
            comment,
            h("button", { class: "btn small icon", type: "button", "aria-label": "Helpful", title: "Helpful", onclick: () => send(1) }, icon("up", 16)),
            h("button", { class: "btn small icon", type: "button", "aria-label": "Not helpful", title: "Not helpful", onclick: () => send(-1) }, icon("down", 16)),
            saved,
          ],
    );
  }

  function answerSheet(msg, index) {
    const live = msg.status === "streaming";
    const r = msg.result;
    const sheet = h("article", { class: `sheet answer${live ? " live" : ""}`, "aria-busy": String(live) });
    const body = h("div", { class: "prose", "aria-live": live ? "off" : "polite" });
    if (msg.status === "error") {
      body.append(h("p", null, msg.text || "No answer was produced."));
    } else if (msg.text) {
      body.append(renderMarkdown(msg.text, onBalloon, citedSet(msg)));
    } else if (live) {
      body.append(
        h("p", { class: "pending" }, msg.sources.length ? "Writing the answer from the sources…" : "Searching the documents…"),
      );
    }
    sheet.append(body);

    if (msg.status === "error") {
      sheet.append(
        h(
          "div",
          { class: "notice bad", role: "alert" },
          icon("warn", 18),
          h("div", null, h("strong", null, "The answer failed. "), msg.error, " Check that the API and the model key are available, then ask again."),
        ),
      );
    }
    if (msg.status === "stopped") {
      sheet.append(h("div", { class: "notice info" }, icon("info", 18), "Stopped. The text above is incomplete."));
    }
    if (r?.invalid_citations?.length) {
      sheet.append(
        h(
          "div",
          { class: "notice bad", role: "alert" },
          icon("warn", 18),
          `The model cited sources that do not exist: ${r.invalid_citations.join(", ")}. Treat those claims as unsupported.`,
        ),
      );
    }
    if (r && !r.found) {
      sheet.append(h("div", { class: "notice info" }, icon("info", 18), "No reliable source found, so nothing was guessed."));
    }
    if (msg.searched && r && msg.searched !== r.question) {
      sheet.append(h("div", { class: "notice info" }, icon("search", 18), h("span", null, "Searched as: ", h("em", null, msg.searched))));
    }
    const block = titleBlock(msg);
    if (block) sheet.append(block);
    const feedback = feedbackRow(msg);
    if (feedback) sheet.append(feedback);
    sheet.addEventListener("click", () => {
      if (state.selected !== index) {
        state.selected = index;
        drawRegister();
      }
    });
    return sheet;
  }

  // ----- Register (parts list) -----

  function toggleRegister() {
    state.registerOpen = !state.registerOpen;
    drawRegister();
  }

  function collapseButton() {
    return h("button", { class: "btn small icon", type: "button", "aria-label": "Hide sources", title: "Hide sources", onclick: toggleRegister }, icon("panelClose", 16));
  }

  function drawRegister() {
    const msg = state.messages[state.selected];
    clear(registerHost);
    root.classList.toggle("register-collapsed", !state.registerOpen);
    if (!state.registerOpen) {
      const n = msg?.role === "assistant" ? msg.sources.length : 0;
      registerHost.append(
        h(
          "button",
          { class: "register-tab", type: "button", "aria-label": "Show sources", title: "Show sources", "aria-expanded": "false", onclick: toggleRegister },
          icon("panelOpen", 18),
          h("span", null, n ? `Sources · ${n}` : "Sources"),
        ),
      );
      return;
    }
    if (!state.messages.length) {
      registerHost.append(
        h(
          "aside",
          { class: "sheet register register-empty", "aria-label": "Sources" },
          h("div", { class: "sheet-head" }, h("h2", null, "Sources"), collapseButton()),
          h("div", { class: "sheet-body" }, h("p", { class: "muted" }, "The sources of each answer are listed here, numbered like the balloons in the text. Superseded versions are struck through.")),
        ),
      );
      return;
    }
    if (!msg || msg.role !== "assistant" || !msg.sources.length) return;
    const cited = citedSet(msg);
    const list = h("ul", { class: "parts" });
    const animate = msg.status === "streaming" && !msg.shown;
    msg.shown = true;

    for (const [i, s] of msg.sources.entries()) {
      const n = i + 1;
      const detail = h("div", { class: "part-detail", hidden: true });
      const row = h(
        "button",
        { class: "part-row", type: "button", "aria-expanded": "false" },
        h("span", { class: `bln static${cited && !cited.has(n) ? " ghost" : ""}`, "aria-hidden": "true" }, String(n)),
        h(
          "span",
          null,
          h("span", { class: "part-title" }, s.title),
          h(
            "span",
            { class: "part-meta" },
            s.location ? h("span", null, s.location) : null,
            cited && !cited.has(n) ? h("span", null, "not cited") : null,
          ),
        ),
        h("span", { class: "part-side" }, revision(s.doc_version, s.is_latest), h("span", { class: "part-score", title: "Relevance score from the reranker, 0 to 1" }, s.score.toFixed(2)), h("span", { class: "part-chev" }, icon("chevron", 16))),
      );
      row.addEventListener("click", () => {
        const open = row.getAttribute("aria-expanded") === "true";
        row.setAttribute("aria-expanded", String(!open));
        detail.hidden = open;
        if (!open && !detail.firstChild) fillDetail(detail, s, fold);
      });
      const fold = () => {
        row.setAttribute("aria-expanded", "false");
        detail.hidden = true;
        row.scrollIntoView({ block: "nearest" });
      };
      row.addEventListener("mouseenter", () => light([n], false));
      row.addEventListener("mouseleave", () => light([], false));
      list.append(
        h(
          "li",
          { class: `part${s.is_latest ? "" : " old"}${animate ? " enter" : ""}`, dataset: { n }, style: `--i:${i}` },
          row,
          detail,
        ),
      );
    }
    registerHost.append(
      h(
        "aside",
        { class: "sheet register", "aria-label": "Sources" },
        h(
          "div",
          { class: "sheet-head" },
          h("h2", null, "Sources"),
          h("span", { class: "note" }, cited ? `${cited.size} of ${msg.sources.length} cited` : `${msg.sources.length} retrieved`),
          collapseButton(),
        ),
        list,
      ),
    );
  }

  function fillDetail(detail, s, fold) {
    append(detail, [h("pre", null, s.text)]);
    const page = s.locator?.page;
    if (page) {
      const slot = h("div");
      const btn = h("button", { class: "btn small", type: "button" }, `Show page ${page}`);
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "Loading page…";
        const url = await api.pageImage(s.doc_id, s.doc_version, page);
        if (url) {
          const alt = `${s.title}, page ${page}`;
          clear(slot).append(
            h(
              "button",
              { class: "page-thumb", type: "button", title: "Click to enlarge", "aria-label": `Enlarge ${alt}`, onclick: () => enlarge(url, alt) },
              h("img", { src: url, alt }),
            ),
          );
          btn.remove();
        } else {
          btn.textContent = "No page preview for this source";
        }
      });
      detail.append(btn, slot);
    }
    detail.append(h("button", { class: "btn small fold", type: "button", onclick: fold }, icon("chevron", 14), "Fold source"));
  }

  function enlarge(url, alt) {
    const dlg = h(
      "dialog",
      { class: "lightbox", "aria-label": alt },
      h("button", { class: "btn icon lightbox-close", type: "button", "aria-label": "Close", title: "Close (Esc)", onclick: () => dlg.close() }, icon("close", 18)),
      h("div", { class: "lightbox-scroll" }, h("img", { src: url, alt })),
    );
    dlg.addEventListener("close", () => dlg.remove());
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg || e.target.classList.contains("lightbox-scroll")) dlg.close();
    });
    document.body.append(dlg);
    dlg.showModal();
  }

  // ----- Composer -----

  const field = h("textarea", {
    class: "textarea",
    rows: "1",
    placeholder: "Ask about stacks, limits, requirements… (English or Deutsch)",
    "aria-label": "Question",
  });
  field.value = state.draft;
  const sendBtn = h("button", { class: "btn primary", type: "button" });
  const composer = h(
    "form",
    { class: "sheet composer" },
    field,
    sendBtn,
    h("p", { class: "hint" }, "Enter sends. Shift+Enter adds a line. Follow-up questions use the conversation above."),
  );

  function fit() {
    field.style.height = "auto";
    field.style.height = `${Math.min(field.scrollHeight, 180)}px`;
  }
  field.addEventListener("input", () => {
    state.draft = field.value;
    fit();
  });
  field.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  });
  composer.addEventListener("submit", (e) => e.preventDefault());
  sendBtn.addEventListener("click", () => (busy() ? state.controller.abort() : submit()));

  function syncButton() {
    clear(sendBtn);
    if (busy()) append(sendBtn, [icon("stop", 16), "Stop"]);
    else append(sendBtn, [icon("send", 16), "Ask"]);
  }

  function submit(text) {
    const question = (text ?? field.value).trim();
    if (!question || busy()) return;
    field.value = "";
    state.draft = "";
    fit();
    ask(question);
  }

  // ----- Asking -----

  async function ask(question) {
    const history = state.messages
      .filter((m) => m.role === "user" || (m.role === "assistant" && m.result))
      .map((m) => ({ role: m.role, content: m.text }));
    state.messages.push({ role: "user", text: question });
    const msg = { role: "assistant", text: "", status: "streaming", sources: [], result: null };
    state.messages.push(msg);
    state.selected = state.messages.length - 1;
    state.controller = new AbortController();
    draw();
    scrollToLatest();

    let frame = 0;
    const paint = () => {
      frame = 0;
      const prose = thread.querySelector(".answer:last-of-type .prose");
      if (!prose) return;
      clear(prose).append(renderMarkdown(msg.text, onBalloon, null));
    };
    try {
      for await (const event of api.askStream(
        {
          question,
          history,
          systems: state.scope.systems,
          doc_types: state.scope.docTypes,
          latest_only: state.scope.latestOnly,
        },
        state.controller.signal,
      )) {
        if (event.type === "sources") {
          msg.sources = event.sources;
          msg.searched = event.search_question;
          drawRegister();
        } else if (event.type === "token") {
          msg.text += event.text;
          if (!frame) frame = requestAnimationFrame(paint);
        } else if (event.type === "done") {
          msg.result = event.result;
          msg.text = event.result.answer;
          msg.sources = event.result.sources;
          msg.status = "done";
        } else if (event.type === "error") {
          msg.status = "error";
          msg.error = event.message;
        }
      }
      if (msg.status === "streaming") msg.status = msg.result ? "done" : "error";
      if (msg.status === "error" && !msg.error) msg.error = "The connection closed before the answer finished.";
    } catch (error) {
      if (error.name === "AbortError") msg.status = "stopped";
      else {
        msg.status = "error";
        msg.error = error.message;
      }
    } finally {
      if (frame) cancelAnimationFrame(frame);
      state.controller = null;
      msg.shown = true;
      draw();
    }
  }

  function scrollToLatest() {
    const last = thread.querySelector(".answer:last-of-type");
    if (last) last.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ----- Frame -----

  function emptyState() {
    const corpus = state.corpus
      ? `${state.corpus.documents} documents, ${state.corpus.chunks.toLocaleString("en")} passages indexed.`
      : "Loading the document registry…";
    return h(
      "section",
      { class: "sheet empty" },
      h("h2", null, "Ask a question about the fuel cell documents."),
      h(
        "p",
        null,
        "Datasheets, parameter sheets, requirements, CAD assemblies, drawings and public reports, in English and German. ",
        "Each claim carries a numbered balloon that points to its source. If the documents do not contain the answer, it says so. ",
        corpus,
      ),
      h(
        "div",
        { class: "examples" },
        EXAMPLES.map(([lang, q]) =>
          h("button", { class: "example", type: "button", onclick: () => submit(q) }, h("span", { class: "lang" }, lang), q),
        ),
      ),
    );
  }

  function draw() {
    const keep = document.activeElement === field;
    clear(thread);
    thread.append(scopeSheet());
    if (!state.messages.length) thread.append(emptyState());
    state.messages.forEach((m, i) => {
      if (m.role === "user") thread.append(h("p", { class: "q" }, m.text));
      else thread.append(answerSheet(m, i));
    });
    thread.append(composer);
    syncButton();
    clearBtn.disabled = !state.messages.length;
    drawRegister();
    if (keep) field.focus();
  }

  draw();
  fit();
  return () => {
    state.draft = field.value;
  };
}
