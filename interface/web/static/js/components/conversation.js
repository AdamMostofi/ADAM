// Conversation — scroll container, empty state, scroll button, transcript export.

import { el } from "../dom.js";

const VOX_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
  <circle cx="12" cy="12" r="3"/>
  <path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>
  <circle cx="12" cy="12" r="8" opacity="0.4"/>
</svg>`;

const ARROW_DOWN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
  <path d="M12 5v14M5 12l7 7 7-7"/>
</svg>`;

export class Conversation {
  constructor({ emptyTitle = "The vox is silent", emptyDescription = "Awaiting transmission. Speak, and the Machine Spirit shall answer.", onDownload } = {}) {
    this.onDownload = onDownload;
    this.messages = [];

    this.emptyState = el("div", { class: "adam-conversation-empty" }, [
      el("div", { class: "adam-conversation-empty-icon", html: VOX_ICON }),
      el("h3", { text: emptyTitle }),
      el("p", { text: emptyDescription }),
    ]);

    this.scrollButton = el("button", {
      class: "adam-scroll-button",
      type: "button",
      "aria-label": "Return to the latest vox",
      title: "Return to the latest vox",
      html: ARROW_DOWN,
      onclick: () => this.scrollToBottom(),
    });

    this.content = el("div", { class: "adam-conversation-content" }, [this.emptyState]);

    this.el = el("div", { class: "adam-conversation", role: "log", "aria-label": "Conversation" }, [
      this.content,
      this.scrollButton,
    ]);

    this.el.addEventListener("scroll", () => this._sync());

    requestAnimationFrame(() => this._sync());
  }

  get isEmpty() {
    return this.messages.length === 0;
  }

  addMessage(role, contentNode) {
    const message = contentNode?.classList?.contains("adam-message")
      ? contentNode
      : el("div", { class: `adam-message is-${role}` }, [contentNode]);
    message.dataset.role = role;
    this.content.append(message);
    this.messages.push({ role, node: message });
    this.emptyState.classList.add("hidden");
    if (!this.restoring) this.scrollToBottom();
    this._sync();
    return message;
  }

  remove(node) {
    this.messages = this.messages.filter((m) => m.node !== node);
    node.remove();
    if (this.messages.length === 0) this.emptyState.classList.remove("hidden");
    this._sync();
  }

  clear() {
    for (const m of this.messages) m.node.remove();
    this.messages = [];
    this.emptyState.classList.remove("hidden");
    this._sync();
  }

  scrollToBottom(behavior = "smooth") {
    this.el.scrollTo({ top: this.el.scrollHeight, behavior });
  }

  isAtBottom() {
    return this.el.scrollHeight - this.el.scrollTop - this.el.clientHeight < 4;
  }

  _sync() {
    const atBottom = this.isAtBottom();
    this.scrollButton.classList.toggle("hidden", atBottom);
  }

  download() {
    if (this.onDownload) return this.onDownload(this.messages);
    const text = this.messages
      .map((m) => `**${m.role === "user" ? "Vox Transmission" : "Machine Spirit"}:** ${m.node.innerText}`)
      .join("\n\n");
    const blob = new Blob([text], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: "adam-transcript.md" });
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }
}
