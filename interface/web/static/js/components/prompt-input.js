// PromptInput — vox channel input: auto-resizing textarea, submit, status.
// Core port of AI Elements `prompt-input.tsx` (attachments/screenshot omitted).

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

const SEND = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
  <path d="M12 19V5M5 12l7-7 7 7"/>
</svg>`;

export class PromptInput {
  constructor({ placeholder = "Open a vox channel…", onSubmit, disabled = false } = {}) {
    this.onSubmit = onSubmit;
    this.disabled = disabled;
    this.status = "ready";
    this.value = "";

    this.textarea = el("textarea", {
      class: "adam-prompt-textarea",
      placeholder,
      rows: "1",
      "aria-label": "Vox channel",
    });

    this.submit = el("button", {
      class: "adam-prompt-submit",
      type: "submit",
      "aria-label": "Transmit",
      title: "Transmit (Enter)",
      html: SEND,
    });

    this.el = el("form", { class: "adam-prompt", role: "form" }, [
      el("div", { class: "adam-prompt-field" }, [this.textarea]),
      this.submit,
    ]);

    this.el.addEventListener("submit", (e) => {
      e.preventDefault();
      this._submit();
    });

    this.textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this._submit();
      }
    });

    this.textarea.addEventListener("input", () => {
      this.value = this.textarea.value;
      this._autoresize();
      this._sync();
    });

    this._autoresize();
    this._sync();
  }

  _autoresize() {
    this.textarea.style.height = "auto";
    this.textarea.style.height = `${Math.min(this.textarea.scrollHeight, 220)}px`;
  }

  _sync() {
    const empty = this.value.trim().length === 0;
    this.submit.classList.toggle("is-disabled", empty || this.disabled);
    this.submit.setAttribute("aria-disabled", String(empty || this.disabled));
    this.submit.disabled = empty || this.disabled;
  }

  _submit() {
    const text = this.value.trim();
    if (!text || this.disabled || this.status === "streaming") return;
    this.textarea.value = "";
    this.value = "";
    this._autoresize();
    this._sync();
    if (this.onSubmit) this.onSubmit({ text });
  }

  get isStreaming() {
    return this.status === "streaming";
  }

  setStatus(status) {
    this.status = status;
    this._sync();
  }

  focus() {
    this.textarea.focus();
  }

  setValue(text) {
    this.textarea.value = text;
    this.value = text;
    this._autoresize();
    this._sync();
  }
}
