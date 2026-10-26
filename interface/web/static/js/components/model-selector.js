// ModelSelector — cogitator mode selector (segmented control).
// Ported from AI Elements `model-selector.tsx` (simplified to a mode picker).

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

export class ModelSelector {
  constructor({
    label = "Cogitator mode",
    value = "full",
    options = [
      { value: "full", label: "Full", description: "Kernel + memory + learning + EQ" },
      { value: "simple", label: "Simple", description: "Memory + EQ only" },
    ],
    onChange,
  } = {}) {
    this.value = value;
    this.options = options;
    this.onChange = onChange;

    this.buttons = new Map();
    const row = el("div", { class: "adam-segment", role: "tablist", "aria-label": label });

    for (const opt of options) {
      const btn = el("button", {
        class: "adam-segment-option",
        type: "button",
        role: "tab",
        "aria-selected": String(opt.value === value),
        "data-value": opt.value,
      }, [
        el("span", { class: "adam-segment-option-label", text: opt.label }),
        el("span", { class: "adam-segment-option-desc", text: opt.description }),
      ]);
      if (opt.value === value) btn.classList.add("is-active");
      btn.addEventListener("click", () => this.setValue(opt.value));
      this.buttons.set(opt.value, btn);
      row.append(btn);
    }

    this.el = el("div", { class: "adam-model-selector" }, [
      el("div", { class: "adam-model-selector-label", text: label }),
      row,
    ]);
  }

  setValue(value) {
    if (!this.options.some((o) => o.value === value)) return;
    this.value = value;
    for (const [v, btn] of this.buttons) {
      btn.classList.toggle("is-active", v === value);
      btn.setAttribute("aria-selected", String(v === value));
    }
    if (this.onChange) this.onChange(value);
  }
}
