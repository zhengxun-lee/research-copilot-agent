import { renderBudgetChart } from "./budget-chart.js";
import { escapeHtml as esc } from "../lib/markdown.js";

export function pairSpans(events) {
  const spans = new Map();
  for (const event of events) {
    if (event.name === "span.started")
      spans.set(event.span_id, {
        id: event.span_id,
        parent: event.parent_span_id,
        start: event.timestamp,
        operation: event.data.operation,
        event,
        status: "open",
        duration: null,
      });
    if (event.name === "span.ended" && spans.has(event.span_id))
      Object.assign(spans.get(event.span_id), {
        duration: event.data.duration_ms,
        status: event.data.status,
        error: event.data.error,
        endEvent: event,
      });
  }
  for (const span of spans.values()) {
    let parent = span.parent,
      depth = 0;
    const seen = new Set([span.id]);
    while (spans.has(parent) && !seen.has(parent)) {
      seen.add(parent);
      depth++;
      parent = spans.get(parent).parent;
    }
    span.depth = depth;
  }
  return [...spans.values()];
}
function waterfall(events) {
  const spans = pairSpans(events);
  if (!spans.length) return '<p class="inspector-note">暂无调用记录</p>';
  const start = Math.min(...spans.map((s) => s.start));
  const length = Math.max(
    1,
    ...spans.map((s) => (s.start - start) * 1000 + (s.duration || 0)),
  );
  return spans
    .map(
      (span) =>
        `<button class="waterfall-row ${span.status === "error" ? "span-error" : ""} ${span.operation.startsWith("recovery") ? "span-recovery" : ""}" data-span-event="${esc((span.status === "error" && span.endEvent ? span.endEvent : span.event).event_id)}" title="${esc(span.operation)} · parent ${esc(span.parent || "root")}"><span style="padding-left:${span.depth * 8}px">${esc(span.operation)}</span><i><b style="left:${((span.start - start) * 100000) / length}%;width:${Math.max(0.3, ((span.duration || 0) / length) * 100)}%"></b></i><small>${span.duration == null ? "open" : span.duration.toFixed(1) + " ms"}</small></button>`,
    )
    .join("");
}
function metricMarkup(values) {
  if (!values) return "<p>尚无指标</p>";
  return `${values.inherited_budget ? '<p class="inspector-note">分支预算包含父节点继承额度；输入/输出 usage 只统计当前 Trace 的实际 API 响应。</p>' : ""}<div class="debug-metrics">${[
    [
      "Input tokens · API",
      values.usage_responses ? values.input_tokens : "—",
      `API reported · ${values.usage_responses} responses / ${values.missing_usage} missing`,
    ],
    [
      "Output tokens · API",
      values.usage_responses ? values.output_tokens : "—",
      `API reported · ${values.usage_responses} responses / ${values.missing_usage} missing`,
    ],
    ...[
      ["TTFT", values.ttft_ms],
      ["TTFR", values.ttfr_ms],
      ["First visible", values.first_visible_ms],
      ["Response", values.duration_ms],
    ].map(([label, value]) => [
      label,
      value == null ? "—" : Number(value).toFixed(1) + " ms",
      value == null ? "Unavailable" : "Client monotonic clock · latest request",
    ]),
    [
      "Throughput",
      values.output_tokens_per_second == null
        ? "—"
        : Number(values.output_tokens_per_second).toFixed(1) + " tok/s",
      values.throughput_source || "Unavailable · requires API usage",
    ],
    [
      "Cost · est.",
      values.cost_estimate == null ? "—" : values.cost_estimate.toFixed(6),
      "Local estimate · configured rates",
    ],
    [
      "Cache hit rate",
      values.cache_hit_rate == null
        ? "—"
        : (values.cache_hit_rate * 100).toFixed(1) + "%",
      "Recorded hits / tool requests",
    ],
    ["Retry schedules", values.retries, "Recorded retry.scheduled events"],
    [
      "Context · est.",
      values.context_utilization_estimate == null
        ? "—"
        : (values.context_utilization_estimate * 100).toFixed(1) + "%",
      "Estimated context budget",
    ],
    [
      "Active elapsed",
      values.live_active_ms == null
        ? values.active_duration_ms == null
          ? "—"
          : values.active_duration_ms.toFixed(1) + " ms"
        : values.live_active_ms.toFixed(1) + " ms",
      "Runtime budget clock · cumulative",
    ],
    [
      "Task elapsed",
      values.total_duration_ms == null
        ? "—"
        : values.total_duration_ms.toFixed(1) + " ms",
      "Local wall time · includes pauses",
    ],
  ]
    .map(
      ([label, value, source]) =>
        `<div title="${esc(source)}" aria-description="${esc(source)}"><small>${label}</small><strong class="metric-value">${esc(value)}</strong></div>`,
    )
    .join("")}</div>`;
}

export function mountDebugger() {
  const tab = document.createElement("button");
  tab.textContent = "Debug";
  tab.dataset.inspectorTab = "debug";
  tab.role = "tab";
  tab.setAttribute("aria-selected", "false");
  document.querySelector(".inspector-tabs").append(tab);
  const pane = document.createElement("section");
  pane.dataset.inspectorPanel = "debug";
  pane.className = "inspector-content";
  pane.hidden = true;
  pane.innerHTML =
    '<div class="panel-caption">METRICS</div><div id="liveMetrics"></div><div class="panel-caption">TOKEN / COST · EST.</div><div id="liveTokenChart"></div><div id="liveCostChart"></div><div class="panel-caption">CALL WATERFALL</div><div id="liveWaterfall"></div><pre id="liveSpanPayload"></pre>';
  document.getElementById("agentInspector").append(pane);
  let liveRun = null,
    liveEvents = [],
    seen = new Set();
  let previousMetrics = null;
  document.addEventListener("research:runtime", ({ detail }) => {
    const status = detail.status;
    if (liveRun !== status.run_id) {
      liveRun = status.run_id;
      liveEvents = [];
      seen.clear();
    }
    for (const event of status.events || []) {
      if (!seen.has(event.event_id)) {
        seen.add(event.event_id);
        liveEvents.push(event);
      }
    }
    if (liveEvents.length > 1200) liveEvents = liveEvents.slice(-1200);
    const liveMetrics = status.metrics
      ? {
          ...status.metrics,
          live_active_ms:
            status.budget?.used?.seconds == null
              ? null
              : status.budget.used.seconds * 1000,
        }
      : null;
    const serialized = JSON.stringify(liveMetrics);
    if (serialized !== previousMetrics) {
      document.getElementById("liveMetrics").innerHTML =
        metricMarkup(liveMetrics);
      previousMetrics = serialized;
    }
    renderBudgetChart(
      document.getElementById("liveTokenChart"),
      liveEvents,
      "tokens",
    );
    renderBudgetChart(
      document.getElementById("liveCostChart"),
      liveEvents,
      "cost",
    );
    document.getElementById("liveWaterfall").innerHTML = waterfall(liveEvents);
    document.querySelectorAll("#liveWaterfall [data-span-event]").forEach(
      (button) =>
        (button.onclick = () => {
          document.getElementById("liveSpanPayload").textContent =
            JSON.stringify(
              liveEvents.find((e) => e.event_id === button.dataset.spanEvent),
              null,
              2,
            );
        }),
    );
  });
}
