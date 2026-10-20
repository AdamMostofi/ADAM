// Reveal — fake streaming: progressively un-hide a rendered message.
// Pure CSS/JS animation; the response is already complete (no real streaming).

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function tokenize(text, mode) {
  if (mode === "letter") return [...text];
  if (mode === "line") return text.split("\n").map((l) => `${l}\n`);
  // word — keep trailing spaces attached so layout is preserved
  return text.match(/\S+\s*/g) ?? [text];
}

function wrapTextNodes(root, mode) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);

  const spans = [];
  for (const node of nodes) {
    const text = node.nodeValue ?? "";
    if (!text.trim()) continue;
    const frag = document.createDocumentFragment();
    for (const token of tokenize(text, mode)) {
      const span = document.createElement("span");
      span.className = "adam-reveal-token";
      span.textContent = token;
      frag.append(span);
      spans.push(span);
    }
    node.replaceWith(frag);
  }
  return spans;
}

export class Reveal {
  constructor({ mode = "word", speed = 20, cursor = true } = {}) {
    this.mode = mode;
    this.speed = speed;
    this.cursor = cursor;
    this.container = document.createElement("div");
    this.container.className = "adam-reveal";
    this._cursor = null;
  }

  get isRevealing() {
    return this._running;
  }

  async show(html) {
    this.container.innerHTML = html;
    const tokens = wrapTextNodes(this.container, this.mode);

    if (this.cursor) this._addCursor();
    if (prefersReducedMotion() || tokens.length === 0) {
      this.container.classList.add("is-done");
      return;
    }

    this._running = true;
    for (const token of tokens) {
      token.classList.add("is-visible");
      if (this._cursor && token.nextSibling === null) this._cursor.remove();
      await sleep(this.speed);
    }
    this._running = false;
    this._cursor?.remove();
    this.container.classList.add("is-done");
  }

  setHtml(html) {
    this.container.innerHTML = html;
    this.container.classList.add("is-done");
  }

  _addCursor() {
    this._cursor = document.createElement("span");
    this._cursor.className = "adam-reveal-cursor";
    this._cursor.setAttribute("aria-hidden", "true");
    this.container.append(this._cursor);
  }
}
