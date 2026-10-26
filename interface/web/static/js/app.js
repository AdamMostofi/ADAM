// ADAM web app — bootstrap, theme, tabs, and chat wiring.

import { api } from "./api.js";
import { Conversation } from "./components/conversation.js";
import { Message } from "./components/message.js";
import { renderMarkdown } from "./components/markdown.js";
import { PromptInput } from "./components/prompt-input.js";
import { Reveal } from "./components/reveal.js";
import { Suggestions } from "./components/suggestion.js";
import { ModelSelector } from "./components/model-selector.js";
import { ThinkingIndicator } from "./components/shimmer.js";

const $ = (sel) => document.querySelector(sel);

const loaders = {};
const loaded = new Set();

function setupTheme() {
  const root = document.documentElement;
  const stored = localStorage.getItem("adam-theme");
  const theme = stored ?? (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  root.setAttribute("data-theme", theme);
  const btn = $("#theme-toggle");
  const sync = () => (btn.textContent = root.getAttribute("data-theme") === "dark" ? "☀" : "☾");
  btn.addEventListener("click", () => {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    localStorage.setItem("adam-theme", next);
    sync();
  });
  sync();
}

function activate(tab) {
  document.querySelectorAll(".tab").forEach((b) => {
    const on = b.dataset.tab === tab;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
  $(`#tab-${tab}`).classList.add("active");
  if (loaders[tab] && !loaded.has(tab)) {
    loaded.add(tab);
    loaders[tab]();
  }
}

function setupTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  tabs.forEach((btn, i) => {
    btn.tabIndex = btn.classList.contains("active") ? 0 : -1;
    btn.addEventListener("click", () => activate(btn.dataset.tab));
    btn.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      activate(next.dataset.tab);
    });
  });
}

function setupChat() {
  const conversation = new Conversation({});
  $("#chat-pane").append(conversation.el);

  const thinking = new ThinkingIndicator();
  thinking.el.classList.add("hidden");

  const mode = new ModelSelector({ label: "Cogitator mode", value: "full" });
  $("#chat-pane").append(mode.el);

  const suggestions = new Suggestions({ label: "Sanctioned inquiries" });
  ["Recite the Litany", "Status of the cogitator", "What is the Machine Spirit?"].forEach((s) =>
    suggestions.add(s, ({ text }) => prompt.setValue(text))
  );

  const prompt = new PromptInput({
    placeholder: "Open a vox channel…",
    onSubmit: ({ text }) => send(text),
  });

  $("#chat-pane").append(suggestions.el, prompt.el, thinking.el);

  let busy = false;

  async function send(text) {
    if (busy) return;
    busy = true;
    prompt.setStatus("streaming");
    thinking.el.classList.remove("hidden");
    conversation.scrollToBottom();

    const user = new Message({ from: "user" });
    user.setContent(document.createTextNode(text));
    conversation.addMessage("user", user.el);

    try {
      const result = await api.chat(text, mode.value);
      const assistant = new Message({ from: "assistant" });
      assistant.addAction({ icon: "copy", label: "Copy", tooltip: "Copy", onClick: () => navigator.clipboard.writeText(result.response) });
      assistant.addAction({ icon: "retry", label: "Retry", tooltip: "Retry", onClick: () => send(text) });
      conversation.addMessage("assistant", assistant.el);

      const reveal = new Reveal({ mode: "word", speed: 14 });
      assistant.content.replaceChildren(reveal.container);
      await reveal.show(renderMarkdown(result.response));
    } catch (err) {
      const errMsg = new Message({ from: "assistant" });
      errMsg.setContent(document.createTextNode(`Vox error: ${err.message}`));
      conversation.addMessage("assistant", errMsg.el);
    } finally {
      thinking.el.classList.add("hidden");
      prompt.setStatus("ready");
      prompt.focus();
      busy = false;
    }
  }

  prompt.focus();
}

function setupMemory() {
  const list = $("#memory-list");
  const search = $("#memory-search");
  const source = $("#memory-source");

  async function load() {
    list.replaceChildren(state("Consulting the archives…"));
    try {
      const q = search.value.trim();
      const data = await api.facts(q);
      const rows = source.value ? data.filter((f) => (f.source || "user") === source.value) : data;
      list.replaceChildren();
      if (rows.length === 0) {
        list.append(state(q ? "No records match that query." : "The vaults stand empty."));
        return;
      }
      for (const f of rows) {
        const src = f.source || "user";
        const meta = `confidence ${pct(f.confidence)}${f.similarity ? ` · similarity ${pct(f.similarity)}` : ""}`;
        list.append(el("div", { class: "list-item" }, [
          el("div", { class: "list-item-head" }, [
            el("div", { class: "list-item-title", text: `${f.subject} ${f.predicate} ${f.object}` }),
            badge(src, `badge-${src}`),
          ]),
          el("div", { class: "list-item-meta", text: meta }),
        ]));
      }
    } catch (err) {
      list.replaceChildren(state(`Vox error: ${err.message}`));
    }
  }

  $("#memory-refresh").addEventListener("click", load);
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });
  source.addEventListener("change", load);
  loaders.memory = load;
}

function setupSkills() {
  const list = $("#skills-list");
  async function load() {
    list.replaceChildren(state("Reviewing the librarium…"));
    try {
      const data = await api.skills();
      list.replaceChildren();
      if (data.length === 0) {
        list.append(state("No skills compiled yet."));
        return;
      }
      for (const s of data) {
        const premises = Array.isArray(s.premises) ? s.premises.length : 0;
        list.append(el("div", { class: "list-item" }, [
          el("div", { class: "list-item-head" }, [
            el("div", { class: "list-item-title", text: s.name }),
            badge(s.domain || "general", "badge-learned"),
          ]),
          el("div", { class: "list-item-meta", text: `${premises} premise${premises === 1 ? "" : "s"} · confidence ${pct(s.confidence)}` }),
        ]));
      }
    } catch (err) {
      list.replaceChildren(state(`Vox error: ${err.message}`));
    }
  }
  $("#skills-refresh").addEventListener("click", load);
  loaders.skills = load;
}

function setupStats() {
  const panel = $("#stats-panel");
  async function load() {
    panel.replaceChildren(state("Interrogating the Machine Spirit…"));
    try {
      const s = await api.stats();
      panel.replaceChildren();
      const rows = [
        ["Facts", s.facts], ["Deduced", s.deduced ?? 0], ["Skills", s.skills],
        ["Graph nodes", s.nodes], ["Graph edges", s.edges],
        ["Contradictions", s.contradictions ?? 0], ["Trace steps", s.trace_steps ?? 0],
        ["EQ baseline", Number(s.baseline).toFixed(2)], ["Mood shift", s.mood_shift],
      ];
      for (const [label, value] of rows) {
        panel.append(el("div", { class: "stat-row" }, [
          el("span", { class: "stat-label", text: label }),
          el("span", { class: "stat-value", text: String(value) }),
        ]));
      }
    } catch (err) {
      panel.replaceChildren(state(`Vox error: ${err.message}`));
    }
  }

  $("#save-btn").addEventListener("click", async () => {
    try { await api.save(); flash("State saved."); } catch (err) { flash(err.message); }
  });
  $("#add-fact-btn").addEventListener("click", () => $("#add-fact-form").classList.toggle("hidden"));
  $("#fact-submit").addEventListener("click", async () => {
    const s = $("#fact-subject").value.trim();
    const p = $("#fact-predicate").value.trim();
    const o = $("#fact-object").value.trim();
    if (!s || !p || !o) return flash("All fields required.");
    try {
      await api.addFact(s, p, o);
      $("#fact-subject").value = $("#fact-predicate").value = $("#fact-object").value = "";
      $("#add-fact-form").classList.add("hidden");
      loaded.delete("memory");
      loaded.delete("graph");
      flash("Fact inscribed.");
    } catch (err) { flash(err.message); }
  });
  loaders.settings = load;
}

function setupGraph() {
  const container = $("#graph-container");
  async function load() {
    try {
      const data = await api.graph();
      if (!window.vis) {
        container.replaceChildren(state("vis.js unavailable."));
        return;
      }
      const palette = {
        user: cssVar("--gold", "#c9a227"),
        deduced: cssVar("--bone-2", "#c8bda4"),
        learned: cssVar("--gold-bright", "#e6c35c"),
        inferred: cssVar("--ash", "#8a8375"),
      };
      const nodes = new window.vis.DataSet((data.nodes || []).map((n) => {
        const source = n.source || "user";
        return {
          id: n.id,
          label: n.label,
          color: { background: palette[source] || palette.user, border: cssVar("--iron", "#3a3733") },
          font: { color: cssVar("--void", "#12110f") },
        };
      }));
      const edges = new window.vis.DataSet((data.edges || []).map((e) => ({
        from: e.from, to: e.to, label: e.label, arrows: "to", color: cssVar("--iron", "#3a3733"), font: { color: cssVar("--ash", "#8a8375"), size: 10 },
      })));
      container.replaceChildren();
      new window.vis.Network(container, { nodes, edges }, {
        nodes: { shape: "dot", size: 12, borderWidth: 2 },
        edges: { width: 1.5, smooth: { type: "continuous" } },
        physics: { stabilization: { iterations: 120 } },
        interaction: { hover: true, tooltipDelay: 200 },
      });
    } catch (err) {
      container.replaceChildren(state(`Vox error: ${err.message}`));
    }
  }
  $("#graph-refresh").addEventListener("click", load);
  loaders.graph = load;
}

function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function pct(value) {
  return `${(Number(value) * 100).toFixed(0)}%`;
}

function badge(text, className) {
  return el("span", { class: `badge ${className}`, text });
}

function state(text) {
  return el("div", { class: "list-state", text });
}

function flash(text) {
  const status = $("#header-status");
  const prev = status.textContent;
  status.textContent = text;
  setTimeout(() => (status.textContent = prev), 1800);
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const child of [].concat(children)) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

document.addEventListener("DOMContentLoaded", () => {
  setupTheme();
  setupTabs();
  setupChat();
  setupMemory();
  setupSkills();
  setupStats();
  setupGraph();
});
