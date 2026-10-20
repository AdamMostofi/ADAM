// Tool — collapsible "Rite of Execution" panel (skill call: params + result).
// Ported from AI Elements `tool.tsx`.

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

const WRENCH = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
  <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.1-2.1z"/>
</svg>`;

const CHEVRON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
  <path d="M6 9l6 6 6-6"/>
</svg>`;

const STATUS = {
  "input-streaming": { label: "Pending", tone: "pending" },
  "input-available": { label: "Running", tone: "running" },
  "output-available": { label: "Completed", tone: "completed" },
  "output-error": { label: "Error", tone: "error" },
  "output-denied": { label: "Denied", tone: "error" },
};

export class Tool {
  constructor({ name = "rite", state = "output-available", input, output, error, defaultOpen = false } = {}) {
    this.state = state;

    this.badge = el("span", { class: "adam-tool-badge", role: "status" });
    this.header = el("button", {
      class: "adam-tool-header",
      type: "button",
      "aria-expanded": String(defaultOpen),
      html: `${WRENCH}`,
    }, [
      el("span", { class: "adam-tool-name" }),
      this.badge,
    ]);
    this.header.append(el("span", { class: "adam-tool-chevron", html: CHEVRON }));
    this.header.addEventListener("click", () => this.toggle());

    this.inputSection = el("div", { class: "adam-tool-section" }, [
      el("h4", { text: "Parameters" }),
      el("pre", { class: "adam-tool-pre" }),
    ]);
    this.outputSection = el("div", { class: "adam-tool-section" }, [
      el("h4", { text: "Result" }),
      el("pre", { class: "adam-tool-pre" }),
    ]);

    this.content = el("div", { class: "adam-tool-content" }, [this.inputSection, this.outputSection]);

    this.el = el("div", { class: "adam-tool", "data-open": String(defaultOpen) }, [
      this.header,
      this.content,
    ]);

    this.setName(name);
    this.setState(state);
    if (input !== undefined) this.setInput(input);
    if (output !== undefined) this.setOutput(output);
    if (error) this.setError(error);
  }

  get isOpen() {
    return this.el.dataset.open === "true";
  }

  setName(name) {
    this.header.querySelector(".adam-tool-name").textContent = name;
  }

  setState(state) {
    this.state = state;
    const info = STATUS[state] ?? { label: state, tone: "pending" };
    this.badge.textContent = info.label;
    this.badge.dataset.tone = info.tone;
    this.el.dataset.state = state;
  }

  toggle() {
    this.setOpen(!this.isOpen);
  }

  setOpen(open) {
    this.el.dataset.open = String(open);
    this.header.setAttribute("aria-expanded", String(open));
  }

  setInput(input) {
    const pre = this.inputSection.querySelector(".adam-tool-pre");
    pre.textContent = typeof input === "string" ? input : JSON.stringify(input, null, 2);
  }

  setOutput(output) {
    const pre = this.outputSection.querySelector(".adam-tool-pre");
    pre.textContent = typeof output === "string" ? output : JSON.stringify(output, null, 2);
    this.outputSection.querySelector("h4").textContent = "Result";
  }

  setError(error) {
    const pre = this.outputSection.querySelector(".adam-tool-pre");
    pre.textContent = typeof error === "string" ? error : JSON.stringify(error, null, 2);
    this.outputSection.querySelector("h4").textContent = "Error";
    this.outputSection.classList.add("is-error");
  }
}
