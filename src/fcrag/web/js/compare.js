// Parameter comparison across systems, from the parameters table.

import { api } from "./api.js";
import { clear, fmt, h, icon, revision } from "./dom.js";

const SYSTEMS = ["System A", "System B", "System C"];
const DEFAULT_KEYS = [
  "rated_net_power",
  "coolant_outlet_temperature_max",
  "membrane_thickness",
  "pt_loading_cathode",
  "design_lifetime",
];

const state = { systems: new Set(SYSTEMS), keys: null, filter: "" };

export async function mount({ main }) {
  clear(main).append(h("div", { class: "sheet" }, h("div", { class: "status-line" }, "Loading parameters…")));
  let keys;
  try {
    keys = await api.parameterKeys();
  } catch (error) {
    clear(main).append(
      h(
        "div",
        { class: "sheet error-state", role: "alert" },
        h("h2", null, "The parameters could not be loaded"),
        h("p", null, error.message),
        h("button", { class: "btn", type: "button", onclick: () => location.reload() }, "Try again"),
      ),
    );
    return;
  }
  if (!keys.length) {
    clear(main).append(
      h("div", { class: "sheet error-state" }, h("h2", null, "No parameters known"), h("p", null, "The parameter store is empty. Ingest the parameter sheets first.")),
    );
    return;
  }
  const labels = Object.fromEntries(keys.map((k) => [k.key, k]));
  if (!state.keys) state.keys = new Set(DEFAULT_KEYS.filter((k) => labels[k]));

  const result = h("div", { "aria-live": "polite" });
  const picker = h("div", { class: "pick" });

  function drawPicker() {
    clear(picker);
    const needle = state.filter.toLowerCase();
    for (const k of keys) {
      if (needle && !`${k.label_en} ${k.label_de} ${k.key}`.toLowerCase().includes(needle)) continue;
      picker.append(
        h(
          "label",
          { class: "check" },
          h("input", {
            type: "checkbox",
            checked: state.keys.has(k.key),
            onchange: (e) => {
              if (e.target.checked) state.keys.add(k.key);
              else state.keys.delete(k.key);
              run();
            },
          }),
          h("span", null, k.label_en),
        ),
      );
    }
    if (!picker.firstChild) picker.append(h("p", { class: "status-line" }, "No parameter matches."));
  }

  async function run() {
    const systems = SYSTEMS.filter((s) => state.systems.has(s));
    const chosen = keys.map((k) => k.key).filter((k) => state.keys.has(k));
    if (!systems.length || !chosen.length) {
      clear(result).append(h("div", { class: "sheet status-line" }, "Pick at least one system and one parameter."));
      return;
    }
    clear(result).append(h("div", { class: "sheet status-line" }, "Comparing…"));
    try {
      const table = await api.compare(systems, chosen);
      clear(result).append(resultSheet(table, systems, chosen, labels));
    } catch (error) {
      clear(result).append(h("div", { class: "sheet notice bad", role: "alert" }, icon("warn", 18), error.message));
    }
  }

  main.replaceChildren(
    h(
      "div",
      { class: "split" },
      h(
        "div",
        { class: "stack" },
        h(
          "section",
          { class: "sheet" },
          h("div", { class: "sheet-head" }, h("h2", null, "Systems")),
          h(
            "div",
            { class: "sheet-body" },
            SYSTEMS.map((s) =>
              h(
                "label",
                { class: "check" },
                h("input", {
                  type: "checkbox",
                  checked: state.systems.has(s),
                  onchange: (e) => {
                    if (e.target.checked) state.systems.add(s);
                    else state.systems.delete(s);
                    run();
                  },
                }),
                s,
              ),
            ),
          ),
        ),
        h(
          "section",
          { class: "sheet" },
          h("div", { class: "sheet-head" }, h("h2", null, "Parameters"), h("span", { class: "note" }, `${keys.length} known`)),
          h(
            "div",
            { class: "sheet-body stack" },
            h("input", {
              class: "input",
              type: "search",
              placeholder: "Filter parameters",
              "aria-label": "Filter parameters",
              value: state.filter,
              oninput: (e) => {
                state.filter = e.target.value;
                drawPicker();
              },
            }),
            picker,
          ),
        ),
      ),
      result,
    ),
  );
  drawPicker();
  run();
}

function cellValue(cell) {
  if (cell.value === null || cell.value === undefined) return h("span", { class: "muted" }, "–");
  const unit = cell.unit && cell.unit !== "–" ? cell.unit : "";
  const value = h("span", { class: "val" }, fmt(cell.value), unit ? h("span", { class: "unit" }, ` ${unit}`) : null);
  if (cell.agree) return value;
  return h("span", { class: "disagree", title: "Current documents state different values" }, icon("warn", 16), value);
}

function resultSheet(table, systems, chosen, labels) {
  const open = new Set();
  const body = h("tbody");

  function draw() {
    clear(body);
    for (const key of chosen) {
      const row = table[key];
      if (!row) continue;
      const isOpen = open.has(key);
      body.append(
        h(
          "tr",
          { class: isOpen ? "open" : "" },
          h(
            "td",
            null,
            h(
              "button",
              {
                class: "row-btn",
                type: "button",
                "aria-expanded": String(isOpen),
                onclick: () => {
                  if (open.has(key)) open.delete(key);
                  else open.add(key);
                  draw();
                },
              },
              labels[key].label_en,
            ),
            h("div", { class: "muted", style: "font-size:var(--step--1)" }, labels[key].label_de),
          ),
          systems.map((s) => h("td", { class: "num" }, cellValue(row[s]))),
        ),
      );
      if (isOpen) {
        const lines = systems.flatMap((s) =>
          row[s].sources.map((src) =>
            h(
              "div",
              { class: "src-line" },
              h("strong", null, s),
              h("span", { class: "val" }, src.stated),
              h("span", null, src.title),
              revision(src.doc_version, src.is_latest),
              h("span", { class: "muted" }, src.location),
            ),
          ),
        );
        body.append(
          h("tr", { class: "detail" }, h("td", { colspan: String(systems.length + 1) }, lines.length ? lines : "No source states this value.")),
        );
      }
    }
  }
  draw();

  return h(
    "section",
    { class: "sheet" },
    h(
      "div",
      { class: "sheet-head" },
      h("h2", null, "Comparison"),
      h("span", { class: "note" }, "Value of the newest version of the preferred document. A warning marks disagreeing documents. Select a row for its sources."),
    ),
    h(
      "div",
      { class: "tbl-wrap" },
      h(
        "table",
        { class: "tbl" },
        h("thead", null, h("tr", null, h("th", { scope: "col" }, h("span", null, "Parameter")), systems.map((s) => h("th", { scope: "col", class: "num" }, h("span", { style: "justify-content:flex-end" }, s))))),
        body,
      ),
    ),
  );
}
