// ADAM web app — bootstrap, theme, tabs, and chat wiring.

import { api } from "./api.js";
import { Conversation } from "./components/conversation.js";
import { Message } from "./components/message.js";
import { markdownToNode, renderMarkdown } from "./components/markdown.js";
import { PromptInput } from "./components/prompt-input.js";
import { Reveal } from "./components/reveal.js";
import { Suggestions } from "./components/suggestion.js";
import { ModelSelector } from "./components/model-selector.js";
import { ThinkingIndicator } from "./components/shimmer.js";

const $ = (sel) => document.querySelector(sel);

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

function setupTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      $(`#tab-${btn.dataset.tab}`).classList.add("active");
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

  async function load() {
    try {
      const q = search.value.trim();
      const data = await api.facts(q);
      list.innerHTML = "";
      if (data.length === 0) {
        list.append(el("div", { class: "list-item" }, [el("div", { class: "list-item-title", text: "The vaults stand empty." })]));
        return;
      }
      for (const f of data) {
        const meta = `confidence ${(f.confidence * 100).toFixed(0)}%${f.similarity ? ` · similarity ${(f.similarity * 100).toFixed(0)}%` : ""}`;
        list.append(el("div", { class: "list-item" }, [
          el("div", { class: "list-item-title", text: `${f.subject} ${f.predicate} ${f.object}` }),
          el("div", { class: "list-item-meta", text: meta }),
        ]));
      }
    } catch (err) {
      list.innerHTML = `<div class="list-item list-item-title">Vox error: ${escapeHtml(err.message)}</div>`;
    }
  }

  $("#memory-refresh").addEventListener("click", load);
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });
  load();
}

function setupSkills() {
  const list = $("#skills-list");
  async function load() {
    try {
      const data = await api.skills();
      list.innerHTML = "";
      if (data.length === 0) {
        list.append(el("div", { class: "list-item" }, [el("div", { class: "list-item-title", text: "No skills compiled yet." })]));
        return;
      }
      for (const s of data) {
        list.append(el("div", { class: "list-item" }, [
          el("div", { class: "list-item-title", text: s.name }),
          el("div", { class: "list-item-meta", text: `${s.domain} · confidence ${(s.confidence * 100).toFixed(0)}%` }),
        ]));
      }
    } catch (err) {
      list.innerHTML = `<div class="list-item list-item-title">Vox error: ${escapeHtml(err.message)}</div>`;
    }
  }
  $("#skills-refresh").addEventListener("click", load);
  load();
}

function setupStats() {
  const panel = $("#stats-panel");
  async function load() {
    try {
      const s = await api.stats();
      panel.innerHTML = "";
      const rows = [
        ["Facts", s.facts], ["Skills", s.skills], ["Graph nodes", s.nodes],
        ["Graph edges", s.edges], ["EQ baseline", s.baseline.toFixed(2)], ["Mood shift", s.mood_shift],
      ];
      for (const [label, value] of rows) {
        panel.append(el("div", { class: "stat-row" }, [
          el("span", { class: "stat-label", text: label }),
          el("span", { class: "stat-value", text: String(value) }),
        ]));
      }
    } catch (err) {
      panel.innerHTML = `<div class="stat-row">Vox error: ${escapeHtml(err.message)}</div>`;
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
      flash("Fact inscribed.");
    } catch (err) { flash(err.message); }
  });
  load();
}

function setupGraph() {
  const container = $("#graph-container");
  async function load() {
    try {
      const data = await api.graph();
      if (!window.vis) {
        container.innerHTML = `<p style="padding:20px;color:var(--ash)">vis.js unavailable.</p>`;
        return;
      }
      const nodes = new window.vis.DataSet((data.nodes || []).map((n) => ({ id: n.id, label: n.label, color: "var(--gold)" })));
      const edges = new window.vis.DataSet((data.edges || []).map((e) => ({ from: e.from, to: e.to, arrows: "to", color: "var(--iron)" })));
      new window.vis.Network(container, { nodes, edges }, {
        nodes: { shape: "dot", size: 12, font: { color: "var(--bone)" } },
        interaction: { hover: true },
      });
    } catch (err) {
      container.innerHTML = `<p style="padding:20px;color:var(--ash)">Vox error: ${escapeHtml(err.message)}</p>`;
    }
  }
  $("#graph-refresh").addEventListener("click", load);
  load();
}

function flash(text) {
  const status = $("#header-status");
  const prev = status.textContent;
  status.textContent = text;
  setTimeout(() => (status.textContent = prev), 1800);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
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

