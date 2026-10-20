// Sources — collapsible "Archived Data" citation list.
// Ported from AI Elements `sources.tsx`.

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

const VAULT = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
  <rect x="4" y="4" width="16" height="16" rx="2"/>
  <path d="M4 9h16M9 4v5"/>
</svg>`;

const CHEVRON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
  <path d="M6 9l6 6 6-6"/>
</svg>`;

export class Source {
  constructor({ title, href, description } = {}) {
    const props = href
      ? { class: "adam-source", href, target: "_blank", rel: "noreferrer" }
      : { class: "adam-source", role: "listitem" };
    this.el = el(href ? "a" : "div", props, [
      el("span", { class: "adam-source-icon", html: VAULT }),
      el("span", { class: "adam-source-text" }, [
        el("span", { class: "adam-source-title", text: title }),
        description ? el("span", { class: "adam-source-desc", text: description }) : null,
      ]),
    ]);
  }
}

export class Sources {
  constructor({ label = "Archived data", defaultOpen = false, sources = [] } = {}) {
    this.items = [];
    this._defaultOpen = defaultOpen;
    this.content = el("div", { class: "adam-sources-content", role: "list" });

    this.trigger = el("button", {
      class: "adam-sources-trigger",
      type: "button",
      "aria-expanded": String(defaultOpen),
      html: `<span class="adam-sources-label">${label}</span><span class="adam-sources-count"></span>${CHEVRON}`,
    });
    this.trigger.addEventListener("click", () => this.setOpen(!this.isOpen));

    this.el = el("div", { class: "adam-sources", "data-open": String(defaultOpen) }, [
      this.trigger,
      this.content,
    ]);

    for (const s of sources) this.add(s);
    this._sync();
  }

  get isOpen() {
    return this.el.dataset.open === "true";
  }

  add(source) {
    const item = source instanceof Source ? source : new Source(source);
    this.items.push(item);
    this.content.append(item.el);
    this._sync();
    if (this._defaultOpen && this.items.length > 0) this.setOpen(true);
    return item;
  }

  setOpen(open) {
    this.el.dataset.open = String(open);
    this.trigger.setAttribute("aria-expanded", String(open));
  }

  _sync() {
    const count = this.trigger.querySelector(".adam-sources-count");
    if (count) count.textContent = `${this.items.length} ${this.items.length === 1 ? "vault" : "vaults"}`;
    if (this.items.length === 0) this.setOpen(false);
  }
}
