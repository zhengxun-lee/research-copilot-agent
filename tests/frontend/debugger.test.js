import test from "node:test";
import assert from "node:assert/strict";
import { pairSpans } from "../../web/components/debugger.js";
import { LiveRuntime } from "../../web/lib/live-stream.js";

test("waterfall uses recorded spans and leaves incomplete calls open", () => {
  const events = [
    {
      name: "span.started",
      span_id: "model",
      parent_span_id: "root",
      timestamp: 10,
      data: { operation: "llm.api" },
    },
    {
      name: "span.started",
      span_id: "tool",
      parent_span_id: "model",
      timestamp: 11,
      data: { operation: "tool" },
    },
    {
      name: "span.ended",
      span_id: "model",
      timestamp: 12,
      data: {
        operation: "llm.api",
        duration_ms: 2000,
        status: "error",
        error: { message: "timeout" },
      },
    },
  ];
  const spans = pairSpans(events);
  assert.equal(spans[0].duration, 2000);
  assert.equal(spans[0].status, "error");
  assert.equal(spans[1].parent, "model");
  assert.equal(spans[1].duration, null);
});

test("SSE client forwards server frames without generating metrics and bounds connections", () => {
  const sources = [];
  class Source {
    constructor(url) {
      this.url = url;
      this.listeners = {};
      sources.push(this);
    }
    addEventListener(name, fn) {
      this.listeners[name] = fn;
    }
    close() {
      this.closed = true;
    }
  }
  globalThis.EventSource = Source;
  const received = [];
  const client = new LiveRuntime((id, status) => received.push({ id, status }));
  assert.equal(client.follow("session-a"), true);
  const status = {
    run_id: "recorded-run",
    state: "thinking",
    events: [],
    metrics: { ttft_ms: null },
  };
  sources[0].listeners.runtime({ data: JSON.stringify(status) });
  assert.deepEqual(received, [{ id: "session-a", status }]);
  assert.deepEqual(client.cached("session-a"), status);
  client.arrivals.set("session-a", Date.now() - 5000);
  assert.equal(client.cached("session-a"), undefined);
  for (const id of ["b", "c", "d"]) client.follow(id);
  assert.equal(client.sources.size, 3);
  assert.equal(sources[0].closed, true);
  client.close();
  assert.equal(client.sources.size, 0);
  delete globalThis.EventSource;
});
