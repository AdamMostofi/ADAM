// Reasoning — collapsible "Machine Deliberation" panel (kernel trace / EQ).
// Ported from AI Elements `reasoning.tsx`.

function el(tag, props = [], children = []) {
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

const COG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
  <circle cx="12" cy="12" r="3.2"/>
  <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1"/>
</svg>`;

const CHEVRON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
  <path d="M6 9l6 6 6-6"/>
</svg>`;

export class Reasoning {
  constructor({ label = "Machine deliberation", defaultOpen = false, duration } = {}) {
    this.isOpen = defaultOpen;
    this.duration = duration;
    this._startedAt = null;
    this._timer = null;

    this.trigger = el("button", {
      class: "adam-reasoning-trigger",
      type: "button",
      "aria-expanded": String(defaultOpen),
      html: `${COG}<span class="adam-reasoning-label">${label}</span><span class="adam-reasoning-status"></span>${CHEVRON}`,
    });
    this.trigger.addEventListener("click", () => this.toggle());

    this.content = el("div", { class: "adam-reasoning-content" });

    this.el = el("div", { class: "adam-reasoning", "data-open": String(defaultOpen) }, [
      this.trigger,
      this.content,
    ]);

    this._sync();
  }

  _sync() {
    this.el.dataset.open = String(this.isOpen);
    this.trigger.setAttribute("aria-expanded", String(this.isOpen));
    const status = this.trigger.querySelector(".adam-reasoning-status");
    if (status) {
      if (this.duration != null) status.textContent = `${this.duration}s`;
      else if (this.isStreaming) status.textContent = "working…";
      else status.textContent = "";
    }
  }

  get isStreaming() {
    return this._startedAt != null;
  }

  toggle() {
    this.setOpen(!this.isOpen);
  }

  setOpen(open) {
    this.isOpen = open;
    this._sync();
  }

  setContent(node) {
    this.content.replaceChildren(node);
    return this;
  }

  setText(text) {
    this.content.replaceChildren(document.createTextNode(text));
    return this;
  }

  start() {
    this._startedAt = Date.now();
    this.setOpen(true);
    this._sync();
  }

  stop() {
    if (this._startedAt != null) {
      this.duration = Math.round((Date.now() - this._startedAt) / 100) / 10;
    }
    this._startedAt = null;
    this.setOpen(false);
    this._sync();
  }
}
