// Requirement checker: stated values against the current documents, plus similar and linked requirements.

import { api } from "./api.js";
import { clear, fmt, h, icon, revision } from "./dom.js";

const SYSTEMS = ["Detect from text", "System A", "System B", "System C"];
const EXAMPLE = "The fuel cell stack shall not exceed a maximum coolant outlet temperature of 90 °C.";
const TONE = { conflict: "bad", consistent: "ok", unknown: "hollow" };
const WORD = { conflict: "Conflict", consistent: "Consistent", unknown: "Not stated in any document" };

const state = { text: EXAMPLE, system: SYSTEMS[2] };

export function mount({ main }) {
  const result = h("div", { "aria-live": "polite" });
  const text = h("textarea", {
    class: "textarea",
    rows: "4",
    "aria-label": "Draft requirement",
    oninput: (e) => (state.text = e.target.value),
  });
  text.value = state.text;
  const system = h(
    "select",
    { class: "select", "aria-label": "System", onchange: (e) => (state.system = e.target.value) },
    SYSTEMS.map((s) => h("option", { value: s, selected: s === state.system }, s)),
  );
  const button = h("button", { class: "btn primary", type: "submit" }, "Check");

  async function check(e) {
    e.preventDefault();
    if (state.text.trim().length < 5) {
      clear(result).append(h("div", { class: "sheet notice bad", role: "alert" }, icon("warn", 18), "Write the requirement first (at least a few words)."));
      return;
    }
    button.disabled = true;
    clear(result).append(h("div", { class: "sheet status-line" }, "Checking against the documents…"));
    try {
      const data = await api.check(state.text, state.system === SYSTEMS[0] ? null : state.system);
      clear(result).append(...render(data));
    } catch (error) {
      clear(result).append(h("div", { class: "sheet notice bad", role: "alert" }, icon("warn", 18), `The check failed: ${error.message}`));
    } finally {
      button.disabled = false;
    }
  }

  main.replaceChildren(
    h(
      "div",
      { class: "stack", style: "max-width:980px" },
      h(
        "form",
        { class: "sheet", onsubmit: check },
        h("div", { class: "sheet-head" }, h("h2", null, "Draft requirement"), h("span", { class: "note" }, "Values are checked against the current documents.")),
        h(
          "div",
          { class: "sheet-body stack" },
          h("div", { class: "field" }, h("label", { class: "label", for: "req-text" }, "Requirement text"), text),
          h("div", { class: "field", style: "max-width:240px" }, h("label", { class: "label", for: "req-system" }, "System"), system),
          h("div", null, button),
        ),
      ),
      result,
    ),
  );
  text.id = "req-text";
  system.id = "req-system";
}

function render(data) {
  if (!data.system) {
    return [
      h("div", { class: "sheet notice info" }, icon("info", 18), "No system found. Name one in the text or pick it above."),
    ];
  }
  const out = [];

  const checks = data.parameters.length
    ? data.parameters.map((c) =>
        h(
          "div",
          { class: "sheet-body", style: "border-top:1px solid var(--hair)" },
          h(
            "div",
            { class: "src-line", style: "align-items:baseline" },
            h("span", { class: `mark ${TONE[c.status]}` }, WORD[c.status]),
            h("strong", null, c.label, c.component ? ` (${c.component})` : ""),
            h("span", null, "draft states ", h("span", { class: "val" }, c.stated)),
          ),
          c.documents.map((d) =>
            h(
              "div",
              { class: "src-line", style: "padding-left:16px" },
              h("span", { class: `mark ${d.agrees ? "ok" : "bad"}` }, d.agrees ? "agrees" : "differs"),
              h("span", { class: "val" }, fmt(d.value), h("span", { class: "unit" }, ` ${c.unit_norm}`)),
              h("span", null, d.title),
              revision(d.doc_version, true), // the API only compares against current versions
              h("span", { class: "muted" }, d.location),
            ),
          ),
        ),
      )
    : [h("div", { class: "status-line" }, "No known parameter with a value was found in the text.")];
  out.push(
    h("section", { class: "sheet" }, h("div", { class: "sheet-head" }, h("h2", null, `Values (${data.system})`)), ...checks),
  );

  out.push(
    h(
      "section",
      { class: "sheet" },
      h("div", { class: "sheet-head" }, h("h2", null, "Similar requirements"), h("span", { class: "note" }, "Best matches in the requirement specifications")),
      data.similar.length
        ? data.similar.map((r) =>
            h(
              "div",
              { class: "sheet-body", style: "border-top:1px solid var(--hair)" },
              h(
                "div",
                { class: "src-line", style: "align-items:baseline" },
                h("strong", { class: "id" }, r.req_id || r.doc_id),
                r.status ? h("span", { class: "mark hollow" }, r.status) : null,
                h("span", { class: "muted" }, `score ${r.score.toFixed(2)}`),
                r.parent ? h("span", { class: "muted" }, `refines ${r.parent}`) : null,
              ),
              h("p", { style: "max-width:74ch" }, r.text),
            ),
          )
        : h("div", { class: "status-line" }, "No similar requirement found."),
    ),
  );

  if (data.linked.length) {
    out.push(
      h(
        "section",
        { class: "sheet" },
        h("div", { class: "sheet-head" }, h("h2", null, "Linked requirements")),
        h("div", { class: "sheet-body" }, h("div", { class: "chips" }, data.linked.map((id) => h("span", { class: "chip id", style: "cursor:default" }, id)))),
      ),
    );
  }
  return out;
}
