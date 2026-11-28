import test from "node:test";
import assert from "node:assert/strict";
import { RuntimeStore } from "../../web/lib/runtime-store.js";

test("recorded runtime export retains independent task results", () => {
  const store = new RuntimeStore();
  store.ingest({
    run_id: "a",
    state: "completed",
    query: "first task",
    result: "first result",
    events: [],
  });
  store.ingest({
    run_id: "b",
    state: "failed",
    query: "second task",
    error: "failure",
    events: [],
  });
  assert.equal(store.export("a").result, "first result");
  assert.equal(store.export("b").error, "failure");
  assert.equal(store.export("b").result, undefined);
});
test("stream fragments never become a completed runtime result", () => {
  const store = new RuntimeStore();
  store.ingest({
    run_id: "a",
    state: "thinking",
    events: [
      {
        event_id: "e",
        run_id: "a",
        name: "llm.stream.delta",
        data: { snapshot: "partial" },
      },
    ],
  });
  const run = store.export("a");
  assert.equal(run.result, undefined);
  assert.equal(run.state, "thinking");
  assert.equal(run.events[0].data.snapshot, "partial");
});
