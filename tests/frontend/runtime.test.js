import test from "node:test";
import assert from "node:assert/strict";
import { RuntimeStore, graphState } from "../../web/lib/runtime-store.js";
import { renderMarkdown } from "../../web/lib/markdown.js";

test("runtime projection only includes observed events for the current run and deduplicates", () => {
  const store = new RuntimeStore();
  const event = {
    event_id: "one",
    run_id: "run-a",
    name: "tool.completed",
    data: { name: "calculator", result: "4" },
  };
  const run = store.ingest(
    {
      run_id: "run-a",
      events: [event, event, { ...event, event_id: "other", run_id: "run-b" }],
      state: "completed",
    },
    { messages: [{ role: "user", content: "2+2" }] },
  );
  assert.equal(run.events.length, 1);
  assert.equal(run.query, "2+2");
  assert.equal(store.export().events[0].data.result, "4");
  assert.equal(store.export().seen, undefined);
});
test("execution graph cannot mark retrieval or final output without the corresponding events", () => {
  const state = graphState({ state: "thinking", running: true }, [
    { name: "run.started" },
    { name: "route.completed" },
  ]);
  assert.equal(state.active, "llm");
  assert.equal(state.visited.has("tools"), false);
  assert.equal(state.visited.has("answer"), false);
});
test("event history stays bounded and reports truncation", () => {
  const store = new RuntimeStore();
  store.ingest({
    run_id: "a",
    events: Array.from({ length: 450 }, (_, i) => ({
      event_id: String(i),
      run_id: "a",
    })),
  });
  assert.equal(store.export().events.length, 400);
  assert.equal(store.export().truncated, true);
});
test("markdown rendering escapes executable markup", () => {
  const html = renderMarkdown(
    "<img src=x onerror=alert(1)>\n```js\n<script>bad()</script>\n```",
  );
  assert.ok(!html.includes("<script>"));
  assert.ok(!html.includes("<img src=x"));
  assert.ok(html.includes("&lt;script&gt;"));
});
test("markdown keeps tables and math fallback", () => {
  assert.ok(
    renderMarkdown("| A | B |\n| --- | --- |\n| 1 | 2 |").includes("<table"),
  );
  assert.ok(renderMarkdown("$$x^2$$").includes("math-block-fallback"));
});

test("restored run uses the server checkpoint query instead of unrelated browser conversation", () => {
  const store = new RuntimeStore();
  const run = store.ingest(
    { run_id: "restored", query: "checkpoint question", events: [] },
    { messages: [{ role: "user", content: "another conversation" }] },
  );
  assert.equal(run.query, "checkpoint question");
});
