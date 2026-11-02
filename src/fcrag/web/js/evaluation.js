// Evaluation: saved runs, the results register for one run against a baseline, recall per
// category, and every failing question with the reason.

import { api } from "./api.js";
import { clear, fmt, h, icon } from "./dom.js";
import { sortableTable } from "./table.js";

// Targets are the plan's v1.0 success criteria (docs/STATUS.md). `higher` says which way is better.
const METRICS = [
  { key: "recall@5", label: "Recall@5", higher: true, target: 0.85, targetText: "≥ 0.85" },
  { key: "recall@10", label: "Recall@10", higher: true },
  { key: "mrr", label: "MRR", higher: true },
  { key: "ndcg@10", label: "nDCG@10", higher: true },
  { key: "value_accuracy", label: "Value accuracy", higher: true, target: 0.85, targetText: "≥ 0.85" },
  { key: "citation_precision", label: "Citation precision", higher: true, target: 0.9, targetText: "≥ 0.90" },
  { key: "faithfulness", label: "Faithfulness (judge)", higher: true, target: 0.9, targetText: "≥ 0.90" },
  { key: "correct_refusal", label: "Correct “not in the documents”", higher: true, target: 0.9, targetText: "≥ 0.90" },
  { key: "false_refusal", label: "False refusals", higher: false },
  { key: "retrieval_p95_s", label: "Retrieval p95 (s)", higher: false, targetText: "< 6 end to end" },
];

const state = { current: null, baseline: null };

function runDate(name) {
  const m = /^(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})/.exec(name);
  return m ? `${m[1]} ${m[2]}:${m[3]}` : "";
}

export async function mount({ main }) {
  clear(main).append(h("div", { class: "sheet" }, h("div", { class: "status-line" }, "Loading the saved runs…")));
  let runs;
  try {
    runs = await api.evalRuns();
  } catch (error) {
    clear(main).append(
      h(
        "div",
        { class: "sheet error-state", role: "alert" },
        h("h2", null, "The evaluation runs could not be loaded"),
        h("p", null, error.message),
        h("p", null, "Runs are read from eval/runs on the machine that runs the API."),
        h("button", { class: "btn", type: "button", onclick: () => location.reload() }, "Try again"),
      ),
    );
    return;
  }
  if (!runs.length) {
    clear(main).append(
      h(
        "div",
        { class: "sheet error-state" },
        h("h2", null, "No runs yet"),
        h("p", null, "Run uv run fcrag eval (add --answers for answer metrics) and reload this page."),
      ),
    );
    return;
  }
  const byName = Object.fromEntries(runs.map((r) => [r.name, r]));
  if (!byName[state.current]) state.current = runs[0].name;
  if (state.baseline && !byName[state.baseline]) state.baseline = null;

  const runsHost = h("div");
  const resultHost = h("div", { class: "stack" });
  main.replaceChildren(h("div", { class: "stack" }, runsHost, resultHost));

  function drawRuns() {
    const columns = [
      {
        key: "label",
        label: "Run",
        cell: (r) =>
          h(
            "button",
            {
              class: "row-btn",
              type: "button",
              "aria-current": r.name === state.current ? "true" : null,
              style: r.name === state.current ? "font-weight:600;color:var(--blue)" : "",
              onclick: () => {
                state.current = r.name;
                if (state.baseline === r.name) state.baseline = null;
                drawRuns();
                drawResult();
              },
            },
            r.label || r.name,
          ),
        value: (r) => r.label || r.name,
      },
      { key: "date", label: "Date", cell: (r) => runDate(r.name), value: (r) => r.name },
      { key: "questions", label: "Questions", num: true, cell: (r) => fmt(r.questions), value: (r) => r.questions },
      { key: "recall@5", label: "Recall@5", num: true, cell: (r) => fmt(r["recall@5"]), value: (r) => r["recall@5"] ?? -1 },
      { key: "mrr", label: "MRR", num: true, cell: (r) => fmt(r.mrr), value: (r) => r.mrr ?? -1 },
      { key: "value_accuracy", label: "Value acc.", num: true, cell: (r) => fmt(r.value_accuracy), value: (r) => r.value_accuracy ?? -1 },
      { key: "citation_precision", label: "Citation prec.", num: true, cell: (r) => fmt(r.citation_precision), value: (r) => r.citation_precision ?? -1 },
      { key: "faithfulness", label: "Faithfulness", num: true, cell: (r) => fmt(r.faithfulness), value: (r) => r.faithfulness ?? -1 },
      { key: "retrieval_p95_s", label: "Retr. p95 (s)", num: true, cell: (r) => fmt(r.retrieval_p95_s), value: (r) => r.retrieval_p95_s ?? -1 },
    ];
    clear(runsHost).append(
      h(
        "section",
        { class: "sheet" },
        h("div", { class: "sheet-head" }, h("h2", null, "Saved runs"), h("span", { class: "note" }, `${runs.length} runs. Select a run name to inspect it.`)),
        sortableTable({ columns, rows: runs, rowKey: (r) => r.name, initial: { key: "date", dir: "desc" }, capped: true }),
      ),
    );
  }

  async function drawResult() {
    const run = byName[state.current];
    const base = state.baseline ? byName[state.baseline] : null;
    clear(resultHost).append(h("div", { class: "sheet status-line" }, `Loading ${run.label || run.name}…`));
    let detail;
    try {
      detail = await api.evalRun(run.name);
    } catch (error) {
      clear(resultHost).append(h("div", { class: "sheet notice bad", role: "alert" }, icon("warn", 18), error.message));
      return;
    }
    if (state.current !== run.name) return;
    clear(resultHost).append(register(run, base, runs), categories(detail), failing(detail));
  }

  drawRuns();
  drawResult();
}

function register(run, base, runs) {
  const select = h(
    "select",
    {
      class: "select",
      style: "max-width:280px",
      "aria-label": "Compare with",
      onchange: (e) => {
        state.baseline = e.target.value || null;
        window.dispatchEvent(new HashChangeEvent("hashchange"));
      },
    },
    h("option", { value: "" }, "No baseline"),
    runs.filter((r) => r.name !== run.name).map((r) => h("option", { value: r.name, selected: r.name === state.baseline }, `${r.label || r.name} (${runDate(r.name)})`)),
  );

  const rows = METRICS.map((m) => {
    const value = run[m.key];
    const prior = base ? base[m.key] : null;
    const delta = value !== null && value !== undefined && prior !== null && prior !== undefined ? value - prior : null;
    let tone = "";
    if (delta !== null && Math.abs(delta) > 0.0005) tone = (delta > 0) === m.higher ? "up" : "down";
    let status = h("span", { class: "muted" }, "–");
    if (m.target !== undefined && value !== null && value !== undefined) {
      const met = value >= m.target;
      status = h("span", { class: `mark ${met ? "ok" : "bad"}` }, met ? "met" : "below target");
    }
    return h(
      "tr",
      null,
      h("td", null, m.label),
      h(
        "td",
        { class: "num" },
        value === null || value === undefined ? h("span", { class: "muted" }, "not measured") : h("span", { class: "val" }, fmt(value)),
      ),
      h("td", { class: "num" }, base ? h("span", { class: "val" }, fmt(prior)) : h("span", { class: "muted" }, "–")),
      h("td", { class: "num" }, delta === null ? h("span", { class: "muted" }, "–") : h("span", { class: `val delta ${tone}` }, `${delta > 0 ? "+" : ""}${fmt(Number(delta.toFixed(3)))}`)),
      h("td", { class: "muted" }, m.targetText || "–"),
      h("td", null, status),
    );
  });

  const changed = base
    ? Object.entries(run.config || {}).filter(([k, v]) => (base.config || {})[k] !== v)
    : [];

  const injection = run.injection;
  return h(
    "section",
    { class: "sheet" },
    h(
      "div",
      { class: "sheet-head" },
      h("h2", null, `Results: ${run.label || run.name}`),
      h("span", { class: "note" }, `${runDate(run.name)} · ${run.questions} questions · ${run.errors || 0} errors`),
    ),
    h("div", { class: "toolbar" }, h("label", { class: "label", for: "baseline" }, "Compare with"), Object.assign(select, { id: "baseline" })),
    h(
      "div",
      { class: "tbl-wrap" },
      h(
        "table",
        { class: "tbl" },
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            ["Metric", "This run", "Baseline", "Change", "Target", "Status"].map((t, i) =>
              h("th", { scope: "col", class: i === 1 || i === 2 || i === 3 ? "num" : "" }, h("span", { style: i >= 1 && i <= 3 ? "justify-content:flex-end" : "" }, t)),
            ),
          ),
        ),
        h("tbody", null, rows),
      ),
    ),
    changed.length
      ? h(
          "div",
          { class: "notice info" },
          icon("info", 18),
          h("span", null, "Configuration differs from the baseline: ", changed.map(([k, v]) => `${k} ${(base.config || {})[k] ?? "unset"} → ${v}`).join("; ")),
        )
      : null,
    injection
      ? h(
          "div",
          { class: "notice info" },
          icon("info", 18),
          h(
            "span",
            null,
            `Prompt injection: ${injection.resisted} of ${injection.questions} answers resisted; the planted note was among the sources in ${injection.planted_in_sources}.`,
            injection.forced ? ` With the note forced in as the first source: ${injection.forced_resisted} of ${injection.forced} resisted.` : "",
          ),
        )
      : null,
  );
}

function categories(detail) {
  const by = detail.summary?.by_category || {};
  const names = Object.keys(by);
  return h(
    "section",
    { class: "sheet" },
    h("div", { class: "sheet-head" }, h("h2", null, "Recall@5 per category"), h("span", { class: "note" }, "Share of questions whose gold source is in the top five")),
    h(
      "div",
      { class: "bars" },
      names.map((name) => {
        const v = by[name]["recall@5"];
        return h(
          "div",
          { class: "bar" },
          h("span", null, name.replace(/_/g, " ")),
          v === null || v === undefined
            ? h("span", { class: "muted" }, "no gold source (refusal category)")
            : h("div", { class: "track", role: "img", "aria-label": `${name}: ${fmt(v)}` }, h("div", { class: `fill${v < 0.8 ? " low" : ""}`, style: `width:${(v * 100).toFixed(1)}%` })),
          h("span", { class: "n val" }, v === null || v === undefined ? `n = ${by[name].n}` : `${fmt(v)}  (n = ${by[name].n})`),
        );
      }),
    ),
  );
}

function problems(r) {
  const issues = [];
  if (r.error) issues.push("error");
  if (r.answerable && r.category !== "unanswerable") {
    if (r.rank === null || r.rank === undefined) issues.push("no gold source retrieved");
    else if (r.rank > 5) issues.push(`gold source at rank ${r.rank}`);
    if (r.refused) issues.push("refused");
  } else if (r.refused === false) {
    issues.push("answered an unanswerable question");
  }
  if (r.values_ok === false) issues.push("wrong or missing value");
  if (r.terms_ok === false) issues.push("missing ID or term");
  if (r.resisted === false) issues.push("followed a planted instruction");
  if (r.forced_resisted === false) issues.push("followed a planted instruction given as a source");
  return issues;
}

function failing(detail) {
  const results = detail.results || [];
  const rows = results.map((r) => ({ ...r, issues: problems(r) })).filter((r) => r.issues.length);
  const answered = results.filter((r) => r.answer);

  const head = h(
    "div",
    { class: "sheet-head" },
    h("h2", null, `Failing questions (${rows.length} of ${results.length})`),
    h("span", { class: "note" }, "Select an ID for the answer and the top sources"),
  );
  if (!rows.length) {
    return h("section", { class: "sheet" }, head, h("div", { class: "status-line" }, h("span", { class: "mark ok" }, "Every question passed what this run measured.")));
  }
  const columns = [
    { key: "id", label: "ID", nowrap: true, cell: (r) => h("span", { class: "id" }, r.id), value: (r) => r.id },
    { key: "category", label: "Category", cell: (r) => r.category.replace(/_/g, " "), value: (r) => r.category },
    { key: "question", label: "Question", cell: (r) => r.question || "–", value: (r) => r.question || "" },
    { key: "issues", label: "Why it failed", cell: (r) => h("span", { class: "mark bad" }, r.issues.join(", ")), value: (r) => r.issues.join(", ") },
    { key: "rank", label: "Rank", num: true, cell: (r) => (r.rank ?? "–"), value: (r) => r.rank ?? 999 },
  ];
  const detailRow = (r) =>
    h(
      "div",
      { class: "stack" },
      r.answer ? h("p", { style: "max-width:74ch;white-space:pre-wrap" }, r.answer) : h("p", { class: "muted" }, "This run has no stored answer for the question."),
      h("div", { class: "src-line" }, h("span", { class: "label" }, "Top sources"), (r.top || []).slice(0, 5).map((t) => h("span", { class: "id" }, t))),
    );
  return h(
    "section",
    { class: "sheet" },
    head,
    sortableTable({ columns, rows, rowKey: (r) => r.id, detail: detailRow, initial: { key: "id", dir: "asc" } }),
    answered.length ? h("div", { class: "notice info" }, icon("info", 18), `${answered.length} answers are stored in this run.`) : null,
  );
}
