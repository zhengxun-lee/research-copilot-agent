const states = new Map();
let library;
export function budgetSamples(events, resource) {
  return events
    .filter(
      (e) =>
        e.name === "budget.updated" &&
        Number.isFinite(e.data.used?.[resource]) &&
        (resource !== "cost" ||
          (e.data.limits?.input_price_per_million > 0 &&
            e.data.limits?.output_price_per_million > 0)),
    )
    .map((e) => [e.timestamp * 1000, e.data.used[resource]]);
}
export function renderBudgetChart(host, events, resource) {
  if (!host) return;
  let state = states.get(host);
  if (!state) {
    state = {};
    states.set(host, state);
  }
  const data = budgetSamples(events, resource);
  const key = JSON.stringify(data);
  if (state.key === key && state.chart) return;
  state.key = key;
  state.data = data;
  state.resource = resource;
  host.classList.add("console-chart");
  if (!data.length) {
    state.chart?.dispose();
    state.observer?.disconnect();
    state.chart = null;
    host.textContent =
      resource === "cost"
        ? "无费用采样 · 需配置输入 / 输出单价"
        : "等待实际预算事件";
    return;
  }
  host.setAttribute(
    "aria-label",
    `${resource}: ${data.length} recorded budget samples, latest ${data.at(-1)[1]}`,
  );
  host.setAttribute("role", "img");
  // Hidden panels render when shown; DOM-only tests retain an accessible numerical summary.
  if (!host.clientWidth) {
    host.textContent = `${resource} · ${data.at(-1)[1]} · ${data.length} recorded samples`;
    return;
  }
  library ||= import("../vendor/console/charts.js");
  library
    .then(({ init }) => {
      if (state.key !== key || !host.isConnected) return;
      if (!state.chart) {
        host.textContent = "";
        state.chart = init(host, null, { renderer: "svg" });
        if (typeof ResizeObserver !== "undefined") {
          state.observer = new ResizeObserver(() => state.chart?.resize());
          state.observer.observe(host);
        }
      }
      draw(state);
    })
    .catch(() => {
      host.textContent = "图表加载失败；数值仍可在事件记录中检查。";
    });
}
function draw(state) {
  const styles = getComputedStyle(document.documentElement);
  const color = styles.getPropertyValue("--primary").trim();
  const muted = styles.getPropertyValue("--quiet").trim();
  const line = styles.getPropertyValue("--line").trim();
  state.chart.setOption(
    {
      animation: false,
      grid: { left: 46, right: 12, top: 12, bottom: 25 },
      tooltip: { trigger: "axis", renderMode: "richText" },
      xAxis: {
        type: "time",
        axisLabel: { color: muted, fontSize: 10 },
        axisLine: { lineStyle: { color: line } },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: muted, fontSize: 10 },
        splitLine: { lineStyle: { color: line } },
        min: 0,
      },
      series: [
        {
          name: state.resource + " · recorded budget",
          type: "line",
          data: state.data,
          symbol: state.data.length === 1 ? "circle" : "none",
          lineStyle: { width: 1.5, color },
          itemStyle: { color },
        },
      ],
    },
    true,
  );
}
typeof document !== "undefined" &&
  document.addEventListener("research:appearance", () => {
    for (const state of states.values()) if (state.chart) draw(state);
  });
if (typeof addEventListener !== "undefined")
  addEventListener(
    "pagehide",
    () => {
      for (const state of states.values()) {
        state.observer?.disconnect();
        state.chart?.dispose();
      }
      states.clear();
    },
    { once: true },
  );
