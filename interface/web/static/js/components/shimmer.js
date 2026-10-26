// Shimmer + Loader — "Machine Spirit is working" indicators.
// Ported from AI Elements `shimmer.tsx` (text shimmer) + a cogitator spinner.

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

export class Shimmer {
  constructor({ text = "The Machine Spirit stirs…", as = "span", duration = 2 } = {}) {
    const tag = as;
    this.el = el(tag, { class: `adam-shimmer is-${tag}` }, [document.createTextNode(text)]);
    this.el.style.setProperty("--shimmer-duration", `${duration}s`);
    return this;
  }
}

const COG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
  <circle cx="12" cy="12" r="3.2"/>
  <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1"/>
</svg>`;

export class Loader {
  constructor({ label = "Opening vox channel…", size = 28 } = {}) {
    this.el = el("div", { class: "adam-loader", role: "status", "aria-live": "polite" }, [
      el("span", { class: "adam-loader-cog", html: COG }),
      el("span", { class: "adam-loader-label", text: label }),
    ]);
    this.el.style.setProperty("--loader-size", `${size}px`);
  }

  setLabel(text) {
    this.el.querySelector(".adam-loader-label").textContent = text;
  }
}

export class ThinkingIndicator {
  constructor({ text = "The Machine Spirit deliberates" } = {}) {
    this.shimmer = new Shimmer({ text });
    this.el = el("div", { class: "adam-thinking", role: "status", "aria-live": "polite" }, [
      el("span", { class: "adam-thinking-cog", html: COG }),
      this.shimmer.el,
    ]);
  }

  setText(text) {
    this.shimmer.el.textContent = text;
  }
}
