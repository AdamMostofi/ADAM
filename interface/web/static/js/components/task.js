// Task — collapsible "Directives" step list.
// Ported from AI Elements `task.tsx`.

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

const SCROLL = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
  <path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h3"/>
</svg>`;

const CHEVRON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
  <path d="M6 9l6 6 6-6"/>
</svg>`;

export class Task {
  constructor({ title = "Directives", defaultOpen = true, items = [] } = {}) {
    this.items = [];

    this.trigger = el("button", {
      class: "adam-task-trigger",
      type: "button",
      "aria-expanded": String(defaultOpen),
      html: `${SCROLL}`,
    }, [el("span", { class: "adam-task-title", text: title })]);
    this.trigger.append(el("span", { class: "adam-task-count" }), el("span", { class: "adam-task-chevron", html: CHEVRON }));
    this.trigger.addEventListener("click", () => this.toggle());

    this.content = el("div", { class: "adam-task-content", role: "list" });

    this.el = el("div", { class: "adam-task", "data-open": String(defaultOpen) }, [
      this.trigger,
      this.content,
    ]);

    for (const item of items) this.add(item);
    this._sync();
  }

  get isOpen() {
    return this.el.dataset.open === "true";
  }

  add({ title, status = "pending" }) {
    const node = el("div", { class: "adam-task-item", role: "listitem", "data-status": status }, [
      el("span", { class: "adam-task-item-marker", "aria-hidden": "true" }),
      el("span", { class: "adam-task-item-title", text: title }),
    ]);
    this.items.push({ node, status });
    this.content.append(node);
    this._sync();
    return node;
  }

  setStatus(index, status) {
    const item = this.items[index];
    if (!item) return;
    item.status = status;
    item.node.dataset.status = status;
    this._sync();
  }

  toggle() {
    this.setOpen(!this.isOpen);
  }

  setOpen(open) {
    this.el.dataset.open = String(open);
    this.trigger.setAttribute("aria-expanded", String(open));
  }

  _sync() {
    const done = this.items.filter((i) => i.status === "done").length;
    const count = this.trigger.querySelector(".adam-task-count");
    if (count) count.textContent = `${done}/${this.items.length}`;
  }
}
