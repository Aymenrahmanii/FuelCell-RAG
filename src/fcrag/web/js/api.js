// Thin client for the FastAPI endpoints. The page never talks to Qdrant or Postgres.

const KEY_NAME = "fcrag_api_key";

export function getKey() {
  try {
    return sessionStorage.getItem(KEY_NAME) || "";
  } catch {
    return "";
  }
}

export function setKey(value) {
  try {
    if (value) sessionStorage.setItem(KEY_NAME, value);
    else sessionStorage.removeItem(KEY_NAME);
  } catch {
    /* private mode: the key then lives only until the next reload */
  }
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function headers(json) {
  const result = {};
  const key = getKey();
  if (key) result["X-API-Key"] = key;
  if (json) result["Content-Type"] = "application/json";
  return result;
}

async function failure(response) {
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("auth-required"));
    return new ApiError(401, "The API needs a valid key.");
  }
  let detail = response.statusText || `HTTP ${response.status}`;
  try {
    const body = await response.json();
    detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
  } catch {
    /* body was not JSON */
  }
  return new ApiError(response.status, detail);
}

async function request(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: headers(body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "The API is not reachable.");
  }
  if (!response.ok) throw await failure(response);
  return response.json();
}

export const api = {
  health: () => request("/health"),
  documents: () => request("/documents"),
  parameterKeys: () => request("/parameters/keys"),
  compare: (systems, keys) => request("/parameters/compare", { method: "POST", body: { systems, keys } }),
  check: (text, system) => request("/requirements/check", { method: "POST", body: { text, system } }),
  evalRuns: () => request("/eval/runs"),
  evalRun: (name) => request(`/eval/runs/${encodeURIComponent(name)}`),
  startIngest: (force = false) => request("/ingest", { method: "POST", body: { force } }),
  ingestStatus: (id) => request(`/ingest/${encodeURIComponent(id)}`),
  feedback: (payload) => request("/feedback", { method: "POST", body: payload }),

  async pageImage(docId, version, page) {
    const response = await fetch(`/documents/${encodeURIComponent(docId)}/v${version}/pages/${page}.png`, {
      headers: headers(false),
    });
    if (!response.ok) return null;
    return URL.createObjectURL(await response.blob());
  },

  // Server-sent events from POST /ask/stream: sources, token..., done | error
  async *askStream(payload, signal) {
    let response;
    try {
      response = await fetch("/ask/stream", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify(payload),
        signal,
      });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new ApiError(0, "The API is not reachable.");
    }
    if (!response.ok) throw await failure(response);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        for (const line of block.split("\n")) {
          if (line.startsWith("data: ")) yield JSON.parse(line.slice(6));
        }
      }
    }
  },
};
