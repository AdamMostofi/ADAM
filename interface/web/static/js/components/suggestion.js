// Suggestion — a row of clickable "sanctioned inquiry" chips.
// Ported from AI Elements `suggestion.tsx`.

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

export class Suggestion {
  constructor({ text, onClick } = {}) {
    this.el = el("button", {
      class: "adam-suggestion",
      type: "button",
      text,
      onclick: () => onClick?.(text),
    });
  }
}

export class Suggestions {
  constructor({ label = "Sanctioned inquiries", children = [] } = {}) {
    this.el = el("div", { class: "adam-suggestions" }, [
      el("div", { class: "adam-suggestions-label", text: label }),
      el("div", { class: "adam-suggestions-row", role: "group", "aria-label": label }, children),
    ]);
  }

  add(text, onClick) {
    const chip = new Suggestion({ text, onClick });
    this.el.querySelector(".adam-suggestions-row").append(chip.el);
    return chip;
  }
}
