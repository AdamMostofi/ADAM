// Markdown — render assistant responses as HTML (marked.js), sanitized by allowlist.

const ALLOWED_TAGS = new Set([
  "p", "br", "strong", "em", "del", "code", "pre", "blockquote",
  "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
  "a", "img", "hr", "table", "thead", "tbody", "tr", "th", "td",
]);

const DROP_TAGS = new Set([
  "script", "style", "iframe", "object", "embed", "link", "meta", "base",
  "frame", "frameset", "form", "input", "button", "select", "textarea",
  "svg", "math", "foreignobject", "template", "audio", "video", "source",
  "track", "canvas", "portal", "noscript",
]);

const NO_ATTRS = new Set();

const ALLOWED_ATTRS = {
  a: new Set(["href", "title"]),
  img: new Set(["src", "alt"]),
  code: new Set(["class"]),
  ol: new Set(["start"]),
  th: new Set(["align"]),
  td: new Set(["align"]),
};

function sanitize(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const walk = (node) => {
    for (const child of [...node.children]) {
      const tag = child.tagName.toLowerCase();
      if (!ALLOWED_TAGS.has(tag)) {
        if (DROP_TAGS.has(tag)) {
          child.remove();
        } else {
          walk(child);
          child.replaceWith(...child.childNodes);
        }
        continue;
      }

      const allowed = ALLOWED_ATTRS[tag] || NO_ATTRS;
      for (const attr of [...child.attributes]) {
        const name = attr.name.toLowerCase();
        if (!allowed.has(name)) {
          child.removeAttribute(attr.name);
          continue;
        }
        if (name === "href" && !isSafeUrl(attr.value, false)) child.removeAttribute(attr.name);
        if (name === "src" && !isSafeUrl(attr.value, true)) child.removeAttribute(attr.name);
      }

      if (tag === "code" && child.hasAttribute("class")) {
        const lang = child.className.match(/language-[a-z0-9_+-]+/i);
        if (lang) child.className = lang[0];
        else child.removeAttribute("class");
      }
      if (tag === "a") child.setAttribute("rel", "noopener noreferrer");
      if (tag === "img") {
        child.setAttribute("loading", "lazy");
        child.setAttribute("referrerpolicy", "no-referrer");
      }

      walk(child);
    }
  };
  walk(doc.body);
  return doc.body.innerHTML;
}

function isSafeUrl(value, image) {
  const v = value.trim().replace(/[\u0000-\u0020]+/g, "");
  if (!v) return false;
  if (!image && v.startsWith("#")) return true;
  if (/^data:/i.test(v)) {
    return image && /^data:image\/(png|jpe?g|gif|webp);base64,[a-z0-9+/=]+$/i.test(v);
  }
  try {
    const url = new URL(v, location.origin);
    if (image) return url.protocol === "http:" || url.protocol === "https:";
    return ["http:", "https:", "mailto:"].includes(url.protocol);
  } catch {
    return false;
  }
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
