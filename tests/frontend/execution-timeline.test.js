import test from "node:test";
import assert from "node:assert/strict";
import { renderExecutionTimeline } from "../../web/lib/execution-timeline.js";

test("execution timeline shows observed tool inputs and results and escapes provider text", () => {
  const html = renderExecutionTimeline([
    { name: "route.completed", data: { model: "unit-model", route: "complex" } },
    { name: "tool.started", data: { name: "search_knowledge", arguments: { query: "attention" } } },
    { name: "tool.completed", data: { result: '<script>evidence</script>' } },
    { name: "llm.stream.delta", data: { snapshot: "unused stream noise" } },
    { name: "run.finished", data: { error: "provider unavailable" }, state: "failed" },
  ]);
  assert.match(html, /深度模型/);
  assert.match(html, /attention/);
  assert.match(html, /观察工具结果/);
  assert.match(html, /&lt;script&gt;evidence/);
  assert.ok(!html.includes("<script>"));
  assert.ok(!html.includes("unused stream noise"));
  assert.match(html, /provider unavailable/);
  assert.match(renderExecutionTimeline([{ name: "tool.started" }]), /调用工具/);
});

test("live updates retain expanded step details and focus while appending new events", async () => {
  const { JSDOM } = await import("jsdom");
  const { updateExecutionTimeline } = await import("../../web/lib/execution-timeline.js");
  const dom = new JSDOM('<ol id="timeline"></ol>');
  const target = dom.window.document.getElementById("timeline");
  const first = { event_id: "tool-1", name: "tool.started", data: { name: "calculator", arguments: { expression: "1+1" } } };
  updateExecutionTimeline(target, [first]);
  const row = target.firstElementChild;
  const details = row.querySelector("details");
  details.open = true;
  details.querySelector("summary").focus();
  const focus = dom.window.document.activeElement;
  target.scrollTop = 40;
  updateExecutionTimeline(target, [first]);
  updateExecutionTimeline(target, [first, { event_id: "tool-2", name: "tool.completed", data: { result: "2" } }]);
  assert.equal(target.firstElementChild, row);
  assert.equal(row.querySelector("details"), details);
  assert.equal(details.open, true);
  assert.equal(dom.window.document.activeElement, focus);
  assert.equal(target.scrollTop, 40);
  assert.equal(target.children.length, 2);
  updateExecutionTimeline(target, [{ event_id: "next-run", name: "run.started" }]);
  assert.equal(target.children.length, 1);
  assert.equal(details.isConnected, false);
  dom.window.close();
});
