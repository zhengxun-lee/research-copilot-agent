import { icon } from "./icons.js";
import { graphState } from "../lib/runtime-store.js";
export const nodes = [
  ["query", "User query", "Input received", "message"],
  ["router", "Model router", "Simple / Complex", "route"],
  ["llm", "Model request", "ReAct execution", "cpu"],
  ["tools", "Tool invocation", "Retrieval · Calculation", "tool"],
  ["answer", "Final response", "Source-backed output", "check"],
];
export function mountGraph(
  root,
  { architecture = false, onSelect = () => {} } = {},
) {
  root.replaceChildren();
  for (const [index, [id, title, label, glyph]] of nodes.entries()) {
    if (index) {
      const edge = document.createElement("div");
      edge.className = "flow-edge";
      edge.dataset.edge = id;
      edge.setAttribute("aria-hidden", "true");
      root.append(edge);
    }
    const node = document.createElement(architecture ? "div" : "button");
    node.className = "flow-node";
    node.dataset.node = id;
    node.innerHTML = `${icon(glyph)}<span>${title}<small>${label}</small></span>${architecture ? "" : '<span class="node-status">—</span>'}`;
    if (!architecture) {
      node.type = "button";
      node.addEventListener("click", () => onSelect(id));
    }
    root.append(node);
  }
  if (architecture) {
    root.classList.add("react-demo");
    root.setAttribute("role", "img");
    root.setAttribute("aria-label", "ReAct 流程演示：用户提问、模型路由、思考、工具调用，观察结果后回到思考，最后生成回答。循环播放。");
    root.querySelector('[data-node="query"] span').innerHTML = "用户提问<small>User query</small>";
    root.querySelector('[data-node="router"] span').innerHTML = "模型路由<small>Simple / Complex</small>";
    root.querySelector('[data-node="llm"] span').innerHTML = "思考<small>Thought · Reasoning</small>";
    root.querySelector('[data-node="tools"] span').innerHTML = "工具调用<small>Action · Observation</small>";
    root.querySelector('[data-node="answer"] span').innerHTML = "生成回答<small>Final response</small>";
    const loop = document.createElement("div");
    loop.className = "react-return";
    loop.setAttribute("aria-hidden", "true");
    loop.innerHTML = '<svg viewBox="0 0 100 48" preserveAspectRatio="none"><path class="react-return-track" d="M100 0V25Q100 36 89 36H11Q0 36 0 25V0"/><path class="react-return-flow" pathLength="100" d="M100 0V25Q100 36 89 36H11Q0 36 0 25V0"/></svg><span>观察结果 → 继续思考</span>';
    root.append(loop);
    if (typeof IntersectionObserver === "function") {
      const observer = new IntersectionObserver(([entry]) => {
        root.classList.toggle("demo-running", entry.isIntersecting);
      }, { threshold: 0.15 });
      observer.observe(root);
    } else {
      root.classList.add("demo-running");
    }
    return () => {};
  }
  return (status, events = []) => {
    const state = graphState(status, events);
    root.querySelectorAll("[data-node]").forEach((el) => {
      const id = el.dataset.node;
      el.classList.toggle("visited", state.visited.has(id));
      el.classList.toggle("active", id === state.active && state.running);
      el.classList.toggle("failed", state.failed && id === state.active);
      el.querySelector(".node-status").textContent =
        id === state.active && state.running
          ? "active"
          : state.visited.has(id)
            ? "seen"
            : "—";
    });
    root
      .querySelectorAll("[data-edge]")
      .forEach((el) =>
        el.classList.toggle(
          "active",
          state.running && el.dataset.edge === state.active,
        ),
      );
  };
}
