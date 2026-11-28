import { escapeHtml as esc } from "./markdown.js";

export const executionEventNames = new Set([
  "run.started", "route.completed", "llm.started", "llm.completed",
  "tool.started", "tool.completed", "tool.failed", "recovery.applied",
  "exception.raised", "run.suspended", "run.finished",
]);

const toolNames = {
  search_knowledge: "检索知识库",
  calculator: "计算",
  summarize_text: "总结文本",
  summarizer: "总结文本",
};
const strategies = {
  model_switch: "切换模型",
  query_rewrite: "调整检索词",
  retrieval_mode_switch: "切换检索方式",
  read_only_tool_retry: "重试工具调用",
  context_pressure_offload: "整理上下文后重试",
  tool_cache_hit: "复用已有工具结果",
  checkpoint_restore: "从检查点恢复",
  local_retrieval_for_budget: "使用本地检索",
};

function describe(event) {
  const d = event.data || {};
  switch (event.name) {
    case "run.started": return ["开始研究", ""];
    case "route.completed": return ["选择模型", [d.model, { simple: "快速模型", complex: "深度模型", default: "默认模型" }[d.route]].filter(Boolean).join(" · ")];
    case "llm.started": return ["请求模型", d.model || ""];
    case "llm.completed": return ["收到模型响应", ""];
    case "tool.started": return [toolNames[d.name] || `调用工具 ${d.name || ""}`, JSON.stringify(d.arguments || {}, null, 2)];
    case "tool.completed": return ["观察工具结果", String(d.result || "工具执行完成")];
    case "tool.failed": return ["工具执行失败", d.error || ""];
    case "recovery.applied": return [strategies[d.strategy] || "调整执行策略", JSON.stringify(d, null, 2)];
    case "exception.raised": return ["执行遇到问题", d.reason || ""];
    case "run.suspended": return ["执行已暂停", ""];
    case "run.finished": return [d.error ? "任务结束，发生错误" : event.state === "cancelled" ? "任务已停止" : "任务结束", d.error || ""];
    default: return null;
  }
}

export function renderExecutionTimeline(events = []) {
  return events.filter((event) => executionEventNames.has(event.name)).slice(-80).map((event) => {
    const [title, detail] = describe(event);
    const time = Number.isFinite(event.timestamp)
      ? new Date(event.timestamp * 1000).toLocaleTimeString() : "";
    const body = detail ? `<details><summary>查看${event.name === "tool.completed" ? "返回结果" : "详情"}</summary><pre>${esc(detail)}</pre></details>` : "";
    const args = event.data?.arguments;
    const input = event.name === "tool.started" ? args?.query || args?.expression : "";
    const preview = typeof input === "string" ? `<p>${esc(input)}</p>` : "";
    return `<li class="execution-step"><time>${esc(time)}</time><div><strong>${esc(title)}</strong>${preview}${event.name === "route.completed" || event.name === "llm.started" ? `<p>${esc(detail)}</p>` : body}</div></li>`;
  }).join("") || '<li class="inspector-empty">此回答暂无可用的执行记录</li>';
}

export function updateExecutionTimeline(target, events = []) {
  const visible = events.filter((event) => executionEventNames.has(event.name)).slice(-80);
  if (!visible.length) {
    if (!target.querySelector(".inspector-empty"))
      target.innerHTML = renderExecutionTimeline([]);
    return;
  }
  target.querySelector(".inspector-empty")?.remove();
  const existing = new Map(
    [...target.children].map((node) => [node.dataset.eventKey, node]),
  );
  const retained = new Set();
  visible.forEach((event, index) => {
    const key = event.event_id || `${event.timestamp}:${event.name}:${index}`;
    retained.add(key);
    if (existing.has(key)) return;
    const template = target.ownerDocument.createElement("template");
    template.innerHTML = renderExecutionTimeline([event]);
    const node = template.content.firstElementChild;
    node.dataset.eventKey = key;
    target.append(node);
  });
  for (const [key, node] of existing) {
    if (!retained.has(key)) node.remove();
  }
}
