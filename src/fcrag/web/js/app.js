import { api, getKey, setKey } from "./api.js";
import { clear, h, icon } from "./dom.js";

const ROUTES = [
  {
    id: "chat",
    label: "Chat",
    icon: "chat",
    title: "Ask the documents",
    sub: "Answers cite a page, table cell, requirement or CAD part.",
    load: () => import("./chat.js"),
  },
  {
    id: "documents",
    label: "Documents",
    icon: "documents",
    title: "Documents",
    sub: "Everything the system has ingested, with its status.",
    load: () => import("./documents.js"),
  },
  {
    id: "parameters",
    label: "Parameters",
    icon: "parameters",
    title: "Parameter comparison",
    sub: "Values per system, straight from the parameters table.",
    load: () => import("./compare.js"),
  },
  {
    id: "requirements",
    label: "Requirements",
    icon: "requirements",
    title: "Requirement checker",
    sub: "Check a draft requirement against the current documents.",
    load: () => import("./checker.js"),
  },
  {
    id: "evaluation",
    label: "Evaluation",
    icon: "evaluation",
    title: "Evaluation",
    sub: "Saved runs of the golden set, and what failed.",
    load: () => import("./evaluation.js"),
  },
];

const main = document.getElementById("main");
const tools = document.getElementById("page-tools");
const titleEl = document.getElementById("page-title");
const subEl = document.getElementById("page-sub");
const nav = document.getElementById("nav");

let cleanup = null;
let token = 0;

for (const route of ROUTES) {
  nav.append(
    h(
      "li",
      null,
      h("a", { href: `#/${route.id}`, dataset: { route: route.id } }, icon(route.icon, 20), h("span", null, route.label)),
    ),
  );
}

function current() {
  const id = location.hash.replace(/^#\//, "").split(/[/?]/)[0];
  return ROUTES.find((r) => r.id === id) || ROUTES[0];
}

async function render() {
  const route = current();
  const mine = ++token;
  if (typeof cleanup === "function") cleanup();
  cleanup = null;
  for (const a of nav.querySelectorAll("a")) {
    if (a.dataset.route === route.id) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  titleEl.textContent = route.title;
  subEl.textContent = route.sub;
  document.title = `${route.title} · FuelCell-RAG`;
  clear(main);
  clear(tools);
  main.scrollTop = 0;
  window.scrollTo(0, 0);
  try {
    const module = await route.load();
    if (mine !== token) return;
    cleanup = (await module.mount({ main, tools })) || null;
  } catch (error) {
    if (mine !== token) return;
    clear(main).append(
      h(
        "div",
        { class: "sheet error-state", role: "alert" },
        h("h2", null, "This screen could not load"),
        h("p", null, error.message || String(error)),
        h("button", { class: "btn", type: "button", onclick: render }, "Try again"),
      ),
    );
  }
}

// ---------- API health ----------

const healthEl = document.getElementById("health");
const keyBtn = document.getElementById("key-btn");

async function checkHealth() {
  try {
    const status = await api.health();
    const ok = status.status === "ok";
    healthEl.dataset.state = ok ? "ok" : "down";
    healthEl.lastChild.textContent = ok ? `API ready · v${status.version}` : `API ${status.status}`;
  } catch (error) {
    healthEl.dataset.state = "down";
    healthEl.lastChild.textContent = error.status === 401 ? "API key needed" : "API not reachable";
  }
  keyBtn.hidden = !(getKey() || healthEl.lastChild.textContent === "API key needed");
}

// ---------- API key dialog ----------

const dialog = document.getElementById("key-dialog");
const keyInput = document.getElementById("key-input");

function askForKey() {
  if (dialog.open) return;
  keyInput.value = "";
  dialog.showModal();
  keyInput.focus();
}

document.getElementById("key-form").addEventListener("submit", () => {
  setKey(keyInput.value.trim());
  checkHealth();
  render();
});
document.getElementById("key-cancel").addEventListener("click", () => dialog.close());
keyBtn.addEventListener("click", askForKey);
window.addEventListener("auth-required", () => {
  keyBtn.hidden = false;
  askForKey();
});

window.addEventListener("hashchange", render);
checkHealth();
setInterval(checkHealth, 30000);
render();
