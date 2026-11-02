// Small DOM helpers. All text goes through text nodes, never innerHTML.

export function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, String(value));
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.firstChild.remove();
  return node;
}

// ---------- Icons: one 1.6 stroke, round caps, 20px ----------

const ICONS = {
  chat: '<path d="M4 5.5h16v10.5H9.5L5.5 20v-4H4z"/>',
  documents: '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5M9 12.5h7M9 16h7"/>',
  parameters: '<path d="M4 5h16v14H4z"/><path d="M4 10h16M9.5 5v14M15 5v14"/>',
  requirements: '<path d="M5 6.5l1.6 1.6L9.5 5M5 12.5l1.6 1.6 2.9-3.1M5 18.5l1.6 1.6 2.9-3.1M12.5 7h7M12.5 13h7M12.5 19h7"/>',
  evaluation: '<path d="M4.5 4v15.5H20"/><path d="M8.5 16v-4M12.5 16V8M16.5 16v-6"/>',
  up: '<path d="M7.5 20H4.5v-9h3zM7.5 11l3.2-6.5a1.7 1.7 0 0 1 3.1 1.3L13 9.5h5a2 2 0 0 1 2 2.3l-1 6.2a2.2 2.2 0 0 1-2.2 2H7.5"/>',
  down: '<path d="M7.5 4H4.5v9h3zM7.5 13l3.2 6.5a1.7 1.7 0 0 0 3.1-1.3L13 14.5h5a2 2 0 0 0 2-2.3l-1-6.2A2.2 2.2 0 0 0 16.8 4H7.5"/>',
  copy: '<path d="M8.5 8.5h11v11h-11z"/><path d="M15.5 8.5V4.5h-11v11h4"/>',
  send: '<path d="M4 12l16-7.5-4.5 15-3.5-6z"/><path d="M12 13.5L20 4.5"/>',
  stop: '<path d="M7 7h10v10H7z"/>',
  trash: '<path d="M5 7h14M9.5 7V4.5h5V7M7 7l.8 12.5h8.4L17 7M10 11v5M14 11v5"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5L20 20"/>',
  chevron: '<path d="M6 9l6 6 6-6"/>',
  warn: '<path d="M12 4l9 15.5H3z"/><path d="M12 10v4.5M12 17v.01"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.01"/>',
  sortUp: '<path d="M7 14l5-5 5 5"/>',
  sortDown: '<path d="M7 10l5 5 5-5"/>',
};

export function icon(name, size = 18) {
  const wrap = document.createElement("span");
  wrap.style.display = "inline-flex";
  wrap.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
  return wrap.firstChild;
}

// Revision triangle, as on a drawing's revision block
export function revision(version, isLatest) {
  const tone = isLatest ? "" : " old";
  const el = document.createElement("span");
  el.className = `rev${tone}`;
  el.innerHTML =
    '<svg width="14" height="13" viewBox="0 0 14 13" fill="none" aria-hidden="true"><path d="M7 1.2l5.6 10.3H1.4z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  el.append(document.createTextNode(`v${version} ${isLatest ? "current" : "superseded"}`));
  return el;
}

// ---------- Formatting ----------

const num = new Intl.NumberFormat("en", { maximumFractionDigits: 3 });
export const fmt = (v) => (v === null || v === undefined ? "–" : num.format(v));
export const fmtS = (v) => (v === null || v === undefined ? "–" : `${v.toFixed(1)} s`);
export const pct = (v) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(1)} %`);

export function when(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

// ---------- Markdown (the subset the model writes) with citation balloons ----------

const CITE = /\[S(\d+)\]/g;

const RUN = /(?:\[S\d+\][ \t]*)+/g;

function rangeLabel(numbers) {
  // [1,2,3,4,5,9] -> "1–5, 9"
  const parts = [];
  let start = numbers[0];
  for (let i = 1; i <= numbers.length; i += 1) {
    if (numbers[i] !== numbers[i - 1] + 1) {
      const end = numbers[i - 1];
      parts.push(end - start >= 2 ? `${start}–${end}` : end === start ? `${start}` : `${start}, ${end}`);
      start = numbers[i];
    }
  }
  return parts.join(", ");
}

function balloon(numbers, onBalloon, cited) {
  const label = numbers.length > 2 ? rangeLabel(numbers) : numbers.join(", ");
  const group = numbers.length > 2;
  const b = h(
    "button",
    {
      type: "button",
      class: `bln${group ? " group" : ""}`,
      "aria-label": `Source${numbers.length > 1 ? "s" : ""} ${label}`,
      dataset: { ns: numbers.join(",") },
    },
    label,
  );
  b.addEventListener("click", () => onBalloon(numbers, false));
  b.addEventListener("mouseenter", () => onBalloon(numbers, true));
  b.addEventListener("focus", () => onBalloon(numbers, true));
  if (cited && numbers.every((n) => !cited.has(n))) b.classList.add("ghost");
  return b;
}

export function citationNodes(text, onBalloon, cited) {
  // A run such as [S1][S2][S3][S4] becomes one range balloon "1–4"; one or two stay separate.
  const out = [];
  let last = 0;
  for (const run of text.matchAll(RUN)) {
    if (run.index > last) out.push(document.createTextNode(text.slice(last, run.index)));
    const numbers = [...new Set([...run[0].matchAll(CITE)].map((m) => Number(m[1])))].sort((a, b) => a - b);
    if (numbers.length > 2) out.push(balloon(numbers, onBalloon, cited));
    else for (const n of numbers) out.push(balloon([n], onBalloon, cited));
    last = run.index + run[0].length;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}

function inline(text, onBalloon, cited) {
  const nodes = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    if (m.index > last) nodes.push(...citationNodes(text.slice(last, m.index), onBalloon, cited));
    const token = m[0];
    if (token.startsWith("**")) nodes.push(h("strong", null, ...citationNodes(token.slice(2, -2), onBalloon, cited)));
    else if (token.startsWith("`")) nodes.push(h("code", null, token.slice(1, -1)));
    else nodes.push(h("em", null, token.slice(1, -1)));
    last = m.index + token.length;
  }
  if (last < text.length) nodes.push(...citationNodes(text.slice(last), onBalloon, cited));
  return nodes;
}

export function renderMarkdown(source, onBalloon = () => {}, cited = null) {
  const root = document.createDocumentFragment();
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const list = h(ordered ? "ol" : "ul");
      while (i < lines.length && (/^\s*[-*•]\s+/.test(lines[i]) || /^\s*\d+[.)]\s+/.test(lines[i]))) {
        const body = lines[i].replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "");
        list.append(h("li", null, ...inline(body, onBalloon, cited)));
        i += 1;
      }
      root.append(list);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const table = h("table");
      table.append(h("thead", null, h("tr", null, ...cells(line).map((c) => h("th", null, ...inline(c, onBalloon, cited))))));
      const body = h("tbody");
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        body.append(h("tr", null, ...cells(lines[i]).map((c) => h("td", null, ...inline(c, onBalloon, cited)))));
        i += 1;
      }
      table.append(body);
      root.append(h("div", { class: "tbl-wrap" }, table));
      continue;
    }
    const para = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
      para.push(lines[i]);
      i += 1;
    }
    root.append(h("p", null, ...inline(para.join(" "), onBalloon, cited)));
  }
  return root;
}
