import { escapeHtml as esc } from "../lib/markdown.js";
export function mountContextPanel() {
  const tabs = document.querySelector(".inspector-tabs");
  const tab = document.createElement("button");
  tab.role = "tab";
  tab.id = "inspector-tab-context";
  tab.dataset.inspectorTab = "context";
  tab.textContent = "Context";
  tab.setAttribute("aria-selected", "false");
  tab.setAttribute("aria-controls", "inspector-context");
  tabs.append(tab);
  const panel = document.createElement("section");
  panel.id = "inspector-context";
  panel.dataset.inspectorPanel = "context";
  panel.className = "inspector-content";
  panel.role = "tabpanel";
  panel.setAttribute("aria-labelledby", tab.id);
  panel.hidden = true;
  panel.innerHTML =
    '<div class="panel-caption">CONTEXT WORKING SET <span>estimated</span></div><div id="contextComposition">暂无上下文记录</div><ol id="contextTimeline" class="runtime-events"></ol>';
  document.getElementById("agentInspector").append(panel);
  let run = null;
  document.addEventListener("research:runtime", ({ detail }) => {
    const status = detail.status;
    if (status.run_id !== run) {
      run = status.run_id;
      document.getElementById("contextTimeline").replaceChildren();
      document.getElementById("contextComposition").textContent =
        "等待上下文组装事件";
    }
    for (const event of status.events || []) {
      if (!event.name.startsWith("context.")) continue;
      const list = document.getElementById("contextTimeline");
      if ([...list.children].some((el) => el.dataset.event === event.event_id))
        continue;
      const item = document.createElement("li");
      item.dataset.event = event.event_id;
      item.className = event.name.includes("restored")
        ? "context-swap-in"
        : event.name.includes("offloaded")
          ? "context-swap-out"
          : "";
      item.textContent =
        event.name +
        " · " +
        (event.data.source || event.data.ref || "working set");
      list.prepend(item);
      while (list.children.length > 40) list.lastChild.remove();
      if (event.name === "context.assembled") {
        const data = event.data;
        document.getElementById("contextComposition").innerHTML =
          `<p class="mono">${data.used} + ${data.reserved} reserved / ${data.window}</p><meter min="0" max="${data.window}" value="${data.used + data.reserved}" aria-label="Estimated context usage"></meter><div class="context-stack">${Object.entries(
            data.categories,
          )
            .map(
              ([name, value], index) =>
                `<span style="flex:${value};background:hsl(${230 + index * 17} 35% ${40 + index * 3}%)" title="${esc(name)}: ${value}"></span>`,
            )
            .join("")}</div><dl>${Object.entries(data.categories)
            .map(
              ([name, value]) =>
                `<div><dt>${esc(name)}</dt><dd>${value}</dd></div>`,
            )
            .join(
              "",
            )}</dl><details><summary>片段溯源 · ${data.fragments.length}</summary><pre>${esc(JSON.stringify(data.fragments, null, 2))}</pre></details>`;
      }
    }
  });
}
