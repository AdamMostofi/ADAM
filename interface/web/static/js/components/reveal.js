// Reveal — progressive un-hide of a completed response, with skip.
// chisel: fixed 3.2s ceiling for 500+ tokens; move to real streaming if transport adds it.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MAX_DURATION = 3200;

export function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function tokenize(text, mode) {
  if (mode === "letter") return [...text];
  if (mode === "line") return text.split("\n").map((l) => `${l}\n`);
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
  constructor({ mode = "word", speed = 16, cursor = true } = {}) {
    this.mode = mode;
    this.speed = speed;
    this.cursor = cursor;
    this.container = document.createElement("div");
    this.container.className = "adam-reveal";
    this._cursor = null;
    this._skipButton = null;
    this._onKey = null;
    this._running = false;
    this._skipped = false;
  }

  get isRevealing() {
    return this._running;
  }

  skip() {
    this._skipped = true;
  }

  async show(html) {
    this.container.innerHTML = html;
    const tokens = wrapTextNodes(this.container, this.mode);

    if (prefersReducedMotion() || tokens.length === 0) {
      this.container.classList.add("is-done");
      return;
    }

    this._running = true;
    this._skipped = false;
    if (this.cursor) this._addCursor();
    this._addSkip();

    const delay = Math.min(this.speed, MAX_DURATION / tokens.length);

    for (const token of tokens) {
      if (this._skipped) {
        tokens.forEach((t) => t.classList.add("is-visible"));
        break;
      }
      token.classList.add("is-visible");
      await sleep(delay);
    }

    this._finish();
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

  _addSkip() {
    this._skipButton = document.createElement("button");
    this._skipButton.className = "adam-reveal-skip";
    this._skipButton.type = "button";
    this._skipButton.textContent = "Skip";
    this._skipButton.setAttribute("aria-label", "Skip response animation");
    this._skipButton.addEventListener("click", () => this.skip());
    this.container.append(this._skipButton);

    this._onKey = (e) => {
      if (e.key === "Escape") this.skip();
    };
    window.addEventListener("keydown", this._onKey);
  }

  _finish() {
    this._running = false;
    this._cursor?.remove();
    this._skipButton?.remove();
    this._cursor = null;
    this._skipButton = null;
    if (this._onKey) window.removeEventListener("keydown", this._onKey);
    this._onKey = null;
    this.container.classList.add("is-done");
  }
}
