// A sortable table with optional expandable detail rows. Headers are real buttons with aria-sort.

import { clear, h, icon } from "./dom.js";

export function sortableTable({ columns, rows, rowKey, detail, initial, wide = false, capped = false }) {
  let sort = initial || null;
  const body = h("tbody");
  const head = h("tr");
  const wrap = h(
    "div",
    { class: `tbl-wrap${capped ? " capped" : ""}` },
    h("table", { class: `tbl${wide ? " wide" : ""}` }, h("thead", null, head), body),
  );
  const open = new Set();

  function order() {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = col.value(a);
      const y = col.value(b);
      if (x === y) return 0;
      return (x > y ? 1 : -1) * sign;
    });
  }

  function drawHead() {
    clear(head);
    for (const col of columns) {
      const active = sort?.key === col.key;
      const th = h("th", { scope: "col", class: col.num ? "num" : "" });
      if (active) th.setAttribute("aria-sort", sort.dir === "asc" ? "ascending" : "descending");
      th.append(
        h(
          "button",
          {
            type: "button",
            onclick: () => {
              sort = { key: col.key, dir: active && sort.dir === "asc" ? "desc" : "asc" };
              drawHead();
              drawBody();
            },
          },
          col.label,
          active ? icon(sort.dir === "asc" ? "sortUp" : "sortDown", 14) : null,
        ),
      );
      head.append(th);
    }
  }

  function drawBody() {
    clear(body);
    for (const row of order()) {
      const key = rowKey(row);
      const isOpen = open.has(key);
      const tr = h("tr", { class: isOpen ? "open" : "" });
      columns.forEach((col, i) => {
        const content = col.cell(row);
        const td = h("td", { class: `${col.num ? "num" : ""}${col.nowrap ? " nowrap" : ""}`.trim() });
        if (i === 0 && detail) {
          td.append(
            h(
              "button",
              {
                class: "row-btn",
                type: "button",
                "aria-expanded": String(isOpen),
                onclick: () => {
                  if (open.has(key)) open.delete(key);
                  else open.add(key);
                  drawBody();
                },
              },
              content,
            ),
          );
        } else td.append(content);
        tr.append(td);
      });
      body.append(tr);
      if (isOpen && detail) {
        body.append(h("tr", { class: "detail" }, h("td", { colspan: String(columns.length) }, detail(row))));
      }
    }
  }

  drawHead();
  drawBody();
  return wrap;
}
