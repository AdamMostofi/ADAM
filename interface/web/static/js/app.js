// ADAM web app — shell, routing, panes, and chat wiring.

import { api } from "./api.js";
import { Chat } from "./chat.js";
import { $, el } from "./dom.js";

const SECTIONS = {
  vox: { crumb: "Vox // Transmission", title: "Conversation" },
  cognition: { crumb: "Cognition // Knowledge Graph", title: "Cognition" },
  vaults: { crumb: "Data-Vaults // Memory", title: "Data-Vaults" },
  skills: { crumb: "Librarium // Compiled Skills", title: "Skills" },
  rites: { crumb: "Rites // System", title: "Rites" },
};

const loaders = {};
const loaded = new Set();
const dirty = new Set();
let activeSection = "vox";
let chatController = null;
let graphNetwork = null;

function setupContrast() {
  const root = document.documentElement;
  const btn = $("#contrast-toggle");
  const stored = localStorage.getItem("adam-contrast");
  const prefersHigh = window.matchMedia?.("(prefers-contrast: more)").matches;
  const mode = stored ?? (prefersHigh ? "high" : "standard");
  root.setAttribute("data-contrast", mode);

  const sync = () => {
    const high = root.getAttribute("data-contrast") === "high";
    btn.setAttribute("aria-pressed", String(high));
    btn.title = high ? "Use standard contrast" : "Use high contrast";
    btn.setAttribute("aria-label", btn.title);
  };
  const apply = (next) => {
    root.setAttribute("data-contrast", next);
    localStorage.setItem("adam-contrast", next);
    sync();
    window.dispatchEvent(new Event("contrastchange"));
  };
  btn.addEventListener("click", () => {
    apply(root.getAttribute("data-contrast") === "high" ? "standard" : "high");
  });
  sync();
}

function setupRail() {
  const app = $("#app");
  const railButtons = [...document.querySelectorAll(".rail-item")];
  const collapse = $("#rail-collapse");

  const setCollapsed = (on) => {
    app.classList.toggle("rail-collapsed", on);
    localStorage.setItem("adam-rail", on ? "collapsed" : "open");
    collapse.textContent = on ? "»" : "«";
    collapse.title = on ? "Expand navigation" : "Collapse navigation";
    collapse.setAttribute("aria-label", collapse.title);
    collapse.setAttribute("aria-expanded", String(!on));
  };
  setCollapsed(localStorage.getItem("adam-rail") === "collapsed");
  collapse.addEventListener("click", () => setCollapsed(!app.classList.contains("rail-collapsed")));

  railButtons.forEach((btn, i) => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.section;
      if (location.hash === `#${name}`) activateSection(name, { focus: true });
      else location.hash = name;
    });
    btn.addEventListener("keydown", (e) => {
      const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
      if (!keys.includes(e.key)) return;
      e.preventDefault();
      let next = i;
      if (e.key === "ArrowDown") next = (i + 1) % railButtons.length;
      if (e.key === "ArrowUp") next = (i - 1 + railButtons.length) % railButtons.length;
      if (e.key === "Home") next = 0;
      if (e.key === "End") next = railButtons.length - 1;
      railButtons[next].focus();
    });
  });

  window.addEventListener("hashchange", () => activateSection(sectionFromHash(), { focus: true }));
}

function sectionFromHash() {
  const name = location.hash.replace("#", "");
  return SECTIONS[name] ? name : "vox";
}

function activateSection(name, { focus = false } = {}) {
  if (!SECTIONS[name]) name = "vox";
  activeSection = name;

  document.querySelectorAll(".rail-item").forEach((btn) => {
    const on = btn.dataset.section === name;
    btn.classList.toggle("is-active", on);
    if (on) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  document.querySelectorAll(".section").forEach((section) => {
    section.classList.toggle("is-active", section.dataset.section === name);
  });

  $("#topbar-crumb").textContent = SECTIONS[name].crumb;
  $("#topbar-title").textContent = SECTIONS[name].title;
  document.title = `${SECTIONS[name].title} · Primarch Adam`;
  renderActions(name);

  if (loaders[name] && (!loaded.has(name) || dirty.has(name))) {
    dirty.delete(name);
    loaded.add(name);
    loaders[name]();
  }
  if (focus) $(`#section-${name}`).focus({ preventScroll: true });
}

function renderActions(name) {
  const actions = [];
  if (name === "vox") {
    actions.push({
      label: "New",
      onClick: () => {
        if (chatController?.clear()) {
          toast("Transcript cleared.", "success");
          refreshTelemetry();
        }
      },
    });
    actions.push({ label: "Export", onClick: () => chatController?.download() });
  } else if (name === "cognition") {
    actions.push({ label: "Fit", onClick: () => graphNetwork?.fit({ animation: { duration: 220, easingFunction: "easeInOutQuad" } }) });
    actions.push({ label: "Refresh", onClick: () => loaders.cognition?.() });
  } else if (name === "vaults") {
    actions.push({ label: "Inscribe", gold: true, onClick: () => toggleFactDrawer() });
  } else if (name === "skills") {
    actions.push({ label: "Refresh", onClick: () => loaders.skills?.() });
  } else if (name === "rites") {
    actions.push({ label: "Save state", gold: true, onClick: saveState });
  }
  $("#topbar-actions").replaceChildren(
    ...actions.map((a) => el("button", {
      class: a.gold ? "gold-btn" : "ghost-btn",
      type: "button",
      text: a.label,
      onclick: a.onClick,
    }))
  );
}

function setupChat() {
  chatController = new Chat({
    mount: $("#chat-pane"),
    onChange: () => {
      invalidate("cognition", "vaults", "skills", "rites");
      refreshTelemetry();
    },
    onToast: (message, tone) => toast(message, tone),
  });
}

function setupMemory() {
  const list = $("#memory-list");
  const search = $("#memory-search");
  const source = $("#memory-source");
  const count = $("#memory-count");
  const panel = $("#add-fact-panel");

  async function load() {
    list.replaceChildren(state("Consulting the archives…"));
    try {
      const q = search.value.trim();
      const data = await api.facts(q);
      const rows = source.value ? data.filter((f) => (f.source || "user") === source.value) : data;
      count.textContent = `${rows.length} record${rows.length === 1 ? "" : "s"}`;
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
      count.textContent = "";
      list.replaceChildren(state(`Vox error: ${err.message}`));
    }
  }

  search.addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });
  source.addEventListener("change", load);

  $("#fact-cancel").addEventListener("click", closeFactDrawer);
  $("#fact-submit").addEventListener("click", submitFact);
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") closeFactDrawer(); });

  loaders.vaults = load;
}

function toggleFactDrawer() {
  const panel = $("#add-fact-panel");
  if (panel.classList.contains("hidden")) {
    panel.classList.remove("hidden");
    $("#fact-subject").focus();
  } else {
    closeFactDrawer();
  }
}

function closeFactDrawer() {
  $("#add-fact-panel").classList.add("hidden");
}

async function submitFact() {
  const s = $("#fact-subject").value.trim();
  const p = $("#fact-predicate").value.trim();
  const o = $("#fact-object").value.trim();
  if (!s || !p || !o) {
    toast("All three fields are required.", "error");
    return;
  }
  try {
    await api.addFact(s, p, o);
    $("#fact-subject").value = $("#fact-predicate").value = $("#fact-object").value = "";
    closeFactDrawer();
    toast("Fact inscribed.", "success");
    invalidate("vaults", "cognition", "rites");
    refreshIfActive("vaults");
    refreshTelemetry();
  } catch (err) {
    toast(err.message, "error");
  }
}

function setupSkills() {
  const list = $("#skills-list");
  const count = $("#skills-count");
  async function load() {
    list.replaceChildren(state("Reviewing the librarium…"));
    try {
      const data = await api.skills();
      count.textContent = `${data.length} skill${data.length === 1 ? "" : "s"}`;
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
      count.textContent = "";
      list.replaceChildren(state(`Vox error: ${err.message}`));
    }
  }
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
      refreshTelemetry(s);
    } catch (err) {
      panel.replaceChildren(state(`Vox error: ${err.message}`));
    }
  }
  loaders.rites = load;
}

async function saveState() {
  try { await api.save(); toast("State saved.", "success"); }
  catch (err) { toast(err.message, "error"); }
}

function setupGraph() {
  const container = $("#graph-container");
  const count = $("#graph-count");
  async function load() {
    try {
      const data = await api.graph();
      const nodeCount = (data.nodes || []).length;
      const edgeCount = (data.edges || []).length;
      count.textContent = `${nodeCount} nodes · ${edgeCount} edges`;
      if (!window.vis) {
        container.replaceChildren(state("vis.js unavailable."));
        return;
      }
      if (nodeCount === 0) {
        container.replaceChildren(state("No connections yet. Inscribe a fact to begin."));
        return;
      }
      const palette = {
        user: cssVar("--metal-gold", "#c9a227"),
        deduced: cssVar("--jewel-sapphire", "#4a6fd8"),
        learned: cssVar("--jewel-emerald", "#2f9e7a"),
        inferred: cssVar("--metal-silver", "#c0c7d0"),
      };
      const nodes = new window.vis.DataSet((data.nodes || []).map((n) => {
        const source = n.source || "user";
        return {
          id: n.id,
          label: n.label,
          color: { background: palette[source] || palette.user, border: cssVar("--edge", "#3a3733") },
          font: { color: cssVar("--surface-0", "#0c0e11") },
        };
      }));
      const edges = new window.vis.DataSet((data.edges || []).map((e) => ({
        from: e.from, to: e.to, label: e.label, arrows: "to", color: cssVar("--edge", "#3a3733"), font: { color: cssVar("--text-mute", "#8a8375"), size: 10 },
      })));
      container.replaceChildren();
      graphNetwork = new window.vis.Network(container, { nodes, edges }, {
        nodes: { shape: "dot", size: 12, borderWidth: 2 },
        edges: { width: 1.5, smooth: { type: "continuous" } },
        physics: { stabilization: { iterations: 120 } },
        interaction: { hover: true, tooltipDelay: 200 },
      });
    } catch (err) {
      count.textContent = "";
      container.replaceChildren(state(`Vox error: ${err.message}`));
    }
  }
  loaders.cognition = load;
  window.addEventListener("contrastchange", () => { if (loaded.has("cognition")) load(); });
}

async function refreshTelemetry(stats) {
  try {
    const s = stats || await api.stats();
    $("#tele-facts").textContent = fmt(s.facts);
    $("#tele-skills").textContent = fmt(s.skills);
    setStatus("Machine spirit online", true);
  } catch {
    setStatus("Machine spirit offline", false);
  }
}

function setStatus(text, online) {
  $("#rail-status-text").textContent = text;
  $("#rail-status").classList.toggle("is-offline", !online);
}

function invalidate(...names) {
  names.forEach((n) => dirty.add(n));
}

function refreshIfActive(name) {
  if (activeSection !== name || !loaders[name]) return;
  dirty.delete(name);
  loaded.add(name);
  loaders[name]();
}

function toast(message, tone = "info") {
  const t = el("div", { class: "toast", "data-tone": tone });
  t.append(
    el("span", { class: "toast-message", text: message }),
    el("button", { class: "toast-close", type: "button", "aria-label": "Dismiss", text: "×" })
  );
  const region = $("#toast-region");
  region.append(t);

  let timer = setTimeout(dismiss, 4000);
  function dismiss() {
    clearTimeout(timer);
    t.classList.add("is-leaving");
    setTimeout(() => t.remove(), 180);
  }
  function pause() { clearTimeout(timer); }
  function resume() { clearTimeout(timer); timer = setTimeout(dismiss, 2000); }
  t.querySelector(".toast-close").addEventListener("click", dismiss);
  t.addEventListener("mouseenter", pause);
  t.addEventListener("mouseleave", resume);
  t.addEventListener("focusin", pause);
  t.addEventListener("focusout", resume);
}

function fmt(n) {
  return Number(n ?? 0).toLocaleString();
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

document.addEventListener("DOMContentLoaded", () => {
  setupContrast();
  setupChat();
  setupMemory();
  setupSkills();
  setupStats();
  setupGraph();
  setupRail();
  refreshTelemetry();
  activateSection(sectionFromHash());
});
