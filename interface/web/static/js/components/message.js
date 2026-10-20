// Message — user/assistant turns, bubbles, actions, toolbar.
// Ported from AI Elements `message.tsx` (vercel/ai-elements).

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

export const ICONS = {
  copy: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="1"/><path d="M5 15V5a1 1 0 0 1 1-1h9"/></svg>`,
  retry: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>`,
  share: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 10.8l7.6-3.6M8.2 13.2l7.6 3.6"/></svg>`,
  like: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M7 22V11L12 2l1.5 5H20a2 2 0 0 1 2 2.3l-1.5 9A2 2 0 0 1 18.5 22H7z"/><path d="M3 11h4v11H3z"/></svg>`,
  dislike: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M7 2v11l5 9 1.5-5H20a2 2 0 0 0 2-2.3l-1.5-9A2 2 0 0 0 18.5 2H7z"/><path d="M3 13h4v9H3z"/></svg>`,
  skull: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M12 2a8 8 0 0 0-8 8c0 3 1.5 5 3.5 6.2V20a2 2 0 0 0 2 2h5a2 2 0 0 0 2-2v-3.8C18.5 15 20 13 20 10a8 8 0 0 0-8-8z"/><circle cx="9" cy="10" r="1.4"/><circle cx="15" cy="10" r="1.4"/><path d="M11 16h2"/></svg>`,
};

export class Message {
  constructor({ from = "assistant", label, actions } = {}) {
    this.from = from;
    this.content = el("div", { class: "adam-message-content" });
    this.actions = el("div", { class: "adam-message-actions hidden" });
    this.toolbar = el("div", { class: "adam-message-toolbar hidden" }, [
      this.actions,
      el("div", { class: "adam-message-branch" }),
    ]);

    const roleLabel = el("div", {
      class: "adam-message-role",
      text: label ?? (from === "user" ? "Vox Transmission" : "Machine Spirit"),
    });

    this.el = el("div", { class: `adam-message is-${from}`, "data-role": from }, [
      roleLabel,
      this.content,
      this.toolbar,
    ]);

    if (actions) for (const action of actions) this.addAction(action);
  }

  get isUser() {
    return this.from === "user";
  }

  setContent(node) {
    const nodes = Array.isArray(node) ? node.flat() : [node];
    this.content.replaceChildren(...nodes);
    return this;
  }

  setText(text) {
    this.content.replaceChildren(document.createTextNode(text));
    return this;
  }

  addAction({ icon, label, tooltip, onClick }) {
    const button = el("button", {
      class: "adam-message-action",
      type: "button",
      "aria-label": label || tooltip,
      title: tooltip || label,
      html: ICONS[icon] ?? icon,
      onclick: onClick,
    });
    this.actions.append(button);
    this.actions.classList.remove("hidden");
    this.toolbar.classList.remove("hidden");
    return button;
  }

  showActions() {
    this.actions.classList.remove("hidden");
    this.toolbar.classList.remove("hidden");
  }

  hideActions() {
    this.actions.classList.add("hidden");
  }
}

export class MessageActions {
  constructor(children = []) {
    this.el = el("div", { class: "adam-message-actions" }, children);
  }
}

export class MessageAction {
  constructor({ icon, label, tooltip, onClick } = {}) {
    this.el = el("button", {
      class: "adam-message-action",
      type: "button",
      "aria-label": label || tooltip,
      title: tooltip || label,
      html: ICONS[icon] ?? icon,
      onclick: onClick,
    });
  }
}

export class MessageToolbar {
  constructor(children = []) {
    this.el = el("div", { class: "adam-message-toolbar" }, children);
  }
}
