// ADAM API client — thin wrapper over the Flask endpoints.

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).error ?? detail;
    } catch {
      /* non-JSON error */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  chat: (message, mode) =>
    request("/api/chat", { method: "POST", body: JSON.stringify({ message, mode }) }),
  facts: (q) => request(`/api/facts${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  addFact: (subject, predicate, object) =>
    request("/api/facts", { method: "POST", body: JSON.stringify({ subject, predicate, object }) }),
  graph: () => request("/api/graph"),
  skills: () => request("/api/skills"),
  stats: () => request("/api/stats"),
  save: () => request("/api/save", { method: "POST", body: "{}" }),
};
