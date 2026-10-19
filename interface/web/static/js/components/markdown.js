// Markdown — render assistant responses as HTML (marked.js), sanitized.
// AI Elements uses Streamdown; we use marked + a small allowlist sanitizer.

const BLOCKED_TAGS = new Set([
  "script", "style", "iframe", "object", "embed", "link", "meta",
  "form", "input", "button", "select", "textarea", "base", "frame", "frameset",
]);
const ALLOWED_SCHEMES = new Set(["http:", "https:", "mailto:", "data:image/"]);

function sanitize(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const walk = (node) => {
    for (const child of [...node.children]) {
      if (BLOCKED_TAGS.has(child.tagName.toLowerCase())) {
        child.remove();
        continue;
      }
      for (const attr of [...child.attributes]) {
        const name = attr.name.toLowerCase();
        const value = attr.value.trim().toLowerCase();
        if (name.startsWith("on")) child.removeAttribute(attr.name);
        else if ((name === "href" || name === "src") && !isSafeUrl(value)) child.removeAttribute(attr.name);
      }
      walk(child);
    }
  };
  walk(doc.body);
  return doc.body.innerHTML;
}

function isSafeUrl(value) {
  if (value.startsWith("#")) return true;
  return [...ALLOWED_SCHEMES].some((scheme) => value.startsWith(scheme));
}

export function renderMarkdown(text) {
  if (!text) return "";
  const raw = window.marked?.parse?.(text) ?? escapeHtml(text);
  return sanitize(raw);
}

export function markdownToNode(text) {
  const div = document.createElement("div");
  div.className = "adam-markdown";
  div.innerHTML = renderMarkdown(text);
  return div;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
