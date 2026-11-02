// Document registry: status, counts, errors, and a re-ingest job.

import { api } from "./api.js";
import { clear, fmt, h, icon, when } from "./dom.js";
import { sortableTable } from "./table.js";

const STATUS_TONE = { indexed: "ok", failed: "bad", quarantined: "bad", queued: "hollow", parsed: "hollow" };

export async function mount({ main, tools }) {
  clear(main).append(h("div", { class: "sheet" }, h("div", { class: "status-line" }, "Loading the registry…")));
  let rows;
  try {
    rows = await api.documents();
  } catch (error) {
    clear(main).append(errorState(error));
    return;
  }

  const view = { status: new Set(), text: "" };
  const counts = {};
  for (const r of rows) counts[r.status] = (counts[r.status] || 0) + 1;

  const figures = h(
    "dl",
    { class: "cells figures", style: "margin:0;border-top:0" },
    figure("Documents", rows.length),
    figure("Document types", new Set(rows.map((r) => r.doc_type).filter(Boolean)).size),
    figure("Passages", rows.reduce((s, r) => s + (r.chunk_count || 0), 0)),
    figure("Failed or quarantined", (counts.failed || 0) + (counts.quarantined || 0)),
  );

  const tableHost = h("div");
  const chips = h(
    "div",
    { class: "chips", role: "group", "aria-label": "Filter by status" },
    Object.keys(counts)
      .sort()
      .map((status) =>
        h(
          "button",
          {
            class: "chip",
            type: "button",
            "aria-pressed": "false",
            onclick: (e) => {
              if (view.status.has(status)) view.status.delete(status);
              else view.status.add(status);
              e.currentTarget.setAttribute("aria-pressed", String(view.status.has(status)));
              drawTable();
            },
          },
          `${status} · ${counts[status]}`,
        ),
      ),
  );
  const search = h("input", {
    class: "input",
    type: "search",
    placeholder: "Filter by title or ID",
    "aria-label": "Filter by title or ID",
    oninput: (e) => {
      view.text = e.target.value.trim().toLowerCase();
      drawTable();
    },
  });

  const columns = [
    {
      key: "doc_id",
      label: "Document",
      cell: (r) => h("span", null, h("div", { class: "doc-title" }, r.title || r.doc_id), h("div", { class: "doc-id" }, r.doc_id)),
      value: (r) => (r.title || r.doc_id).toLowerCase(),
    },
    { key: "doc_version", label: "Ver", num: true, cell: (r) => `v${r.doc_version}`, value: (r) => r.doc_version },
    {
      key: "status",
      label: "Status",
      cell: (r) => h("span", { class: `mark ${STATUS_TONE[r.status] || "hollow"}` }, r.status),
      value: (r) => r.status,
    },
    { key: "doc_type", label: "Type", cell: (r) => r.doc_type || "–", value: (r) => r.doc_type || "" },
    { key: "system", label: "System", cell: (r) => r.system || "–", value: (r) => r.system || "" },
    { key: "language", label: "Lang", cell: (r) => (r.language || "–").toUpperCase(), value: (r) => r.language || "" },
    { key: "chunk_count", label: "Passages", num: true, cell: (r) => fmt(r.chunk_count), value: (r) => r.chunk_count ?? -1 },
    { key: "updated_at", label: "Updated", nowrap: true, cell: (r) => when(r.updated_at), value: (r) => r.updated_at || "" },
  ];

  function detail(r) {
    const item = (label, value) => h("div", { class: "cell" }, h("dt", null, label), h("dd", null, value));
    return h(
      "dl",
      { class: "cells-wrap", style: "margin:0" },
      item("Licence", r.licence || "–"),
      item("Elements", fmt(r.element_count)),
      item("Parse time", r.duration_s ? `${r.duration_s.toFixed(1)} s` : "–"),
      item("Attempts", fmt(r.attempts)),
      r.error ? item("Error", h("span", { style: "color:var(--red)" }, r.error)) : null,
      item("SHA-256", h("span", { class: "id" }, (r.sha256 || "").slice(0, 16))),
    );
  }

  function drawTable() {
    const shown = rows.filter(
      (r) =>
        (!view.status.size || view.status.has(r.status)) &&
        (!view.text || `${r.doc_id} ${r.title || ""}`.toLowerCase().includes(view.text)),
    );
    clear(tableHost).append(
      shown.length
        ? sortableTable({ columns, rows: shown, rowKey: (r) => r.source_key, detail, initial: { key: "doc_id", dir: "asc" }, wide: true })
        : h("div", { class: "status-line" }, "No document matches this filter."),
    );
    count.textContent = `${shown.length} of ${rows.length}`;
  }

  const count = h("span", { class: "note" });
  main.replaceChildren(
    h(
      "div",
      { class: "stack" },
      h("section", { class: "sheet" }, figures),
      h(
        "section",
        { class: "sheet" },
        h("div", { class: "toolbar" }, chips, h("span", { class: "spacer" }), search, count),
        tableHost,
      ),
      ingestSheet(),
    ),
  );
  drawTable();
}

function figure(label, value) {
  return h("div", { class: "cell" }, h("dt", null, label), h("dd", null, fmt(value)));
}

function errorState(error) {
  return h(
    "div",
    { class: "sheet error-state", role: "alert" },
    h("h2", null, "The registry could not be loaded"),
    h("p", null, error.message),
    h("button", { class: "btn", type: "button", onclick: () => location.reload() }, "Try again"),
  );
}

function ingestSheet() {
  const out = h("div", { class: "status-line", role: "status", "aria-live": "polite" }, "No job started in this session.");
  const run = h("button", { class: "btn primary", type: "button" }, icon("refresh", 16), "Re-ingest now");
  let timer = 0;

  async function poll(id) {
    try {
      const status = await api.ingestStatus(id);
      const done = ["finished", "failed", "stopped", "canceled"].includes(status.status);
      clear(out).append(
        h("span", { class: `mark ${status.status === "failed" ? "bad" : done ? "ok" : "hollow"}` }, `Job ${id.slice(0, 8)}: ${status.status}`),
        status.result ? h("span", { class: "id" }, JSON.stringify(status.result)) : null,
      );
      if (!done) timer = setTimeout(() => poll(id), 2000);
      else run.disabled = false;
    } catch (error) {
      out.textContent = `Could not read the job status: ${error.message}`;
      run.disabled = false;
    }
  }

  run.addEventListener("click", async () => {
    run.disabled = true;
    out.textContent = "Queueing…";
    try {
      const { job_id } = await api.startIngest(false);
      poll(job_id);
    } catch (error) {
      out.textContent = `Could not queue the job. Is the worker's Redis reachable? ${error.message}`;
      run.disabled = false;
    }
  });

  return h(
    "section",
    { class: "sheet" },
    h("div", { class: "sheet-head" }, h("h2", null, "Re-ingest"), h("span", { class: "note" }, "Only new or changed files are processed; unchanged files are skipped by content hash.")),
    h("div", { class: "toolbar", style: "border-bottom:0" }, run, out),
  );
}
