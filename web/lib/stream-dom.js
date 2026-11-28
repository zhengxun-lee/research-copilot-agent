import { renderMarkdown } from "./markdown.js";

// Patch existing nodes: do not replay entrance animations or reset selection/details
// each time the server delivers a cumulative snapshot.
export function patchMarkdown(target, text) {
  if (target._streamText === text) return;
  target._streamText = text;
  const template = target.ownerDocument.createElement("template");
  template.innerHTML = renderMarkdown(text || "");
  reconcile(target, template.content);
}
function reconcile(target, source) {
  const wanted = [...source.childNodes];
  for (let i = 0; i < wanted.length; i++) {
    const next = wanted[i],
      current = target.childNodes[i];
    if (!current) {
      target.append(next.cloneNode(true));
      continue;
    }
    if (
      current.nodeType !== next.nodeType ||
      current.nodeName !== next.nodeName
    ) {
      current.replaceWith(next.cloneNode(true));
      continue;
    }
    if (current.nodeType === 3) {
      if (current.data !== next.data) current.data = next.data;
    } else if (current.nodeType === 1) {
      for (const attr of [...current.attributes])
        if (!next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
      for (const attr of next.attributes)
        if (current.getAttribute(attr.name) !== attr.value)
          current.setAttribute(attr.name, attr.value);
      reconcile(current, next);
    }
  }
  while (target.childNodes.length > wanted.length) target.lastChild.remove();
}
export function updateStreamArticle(article, message) {
  const body = article.querySelector(".message-body");
  const output = article.querySelector("[data-stream-output]");
  if (!output || !body) return false;
  patchMarkdown(output, message.content);
  if (message.reasoning) {
    let details = body.querySelector(".provider-reasoning");
    if (!details) {
      details = body.ownerDocument.createElement("details");
      details.className = "provider-reasoning";
      const summary = body.ownerDocument.createElement("summary");
      summary.textContent = "供应商提供的推理输出";
      const text = body.ownerDocument.createElement("div");
      details.append(summary, text);
      output.before(details);
    }
    patchMarkdown(details.querySelector("div"), message.reasoning);
  }
  if (message.content || message.reasoning)
    body.querySelector(".loading-dots")?.remove();
  return true;
}
