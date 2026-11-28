import test from "node:test";
import assert from "node:assert/strict";
import {
  applyStreamSnapshot,
  replayStream,
} from "../../web/lib/stream-state.js";
import { renderMarkdown } from "../../web/lib/markdown.js";
test("stream snapshots survive duplicates and reject stale sequence", () => {
  const m = {};
  const s = {
    stream_id: "a",
    sequence: 2,
    content: "hello",
    reasoning: "provider",
    complete: false,
  };
  assert.equal(applyStreamSnapshot(m, s), true);
  assert.equal(applyStreamSnapshot(m, s), false);
  assert.equal(
    applyStreamSnapshot(m, { ...s, sequence: 1, content: "old" }),
    false,
  );
  assert.equal(m.content, "hello");
  applyStreamSnapshot(m, {
    ...s,
    stream_id: "b",
    sequence: 1,
    content: "next",
  });
  assert.equal(m.content, "next");
});
test("offline stream projection applies snapshots without executing anything", () => {
  const events = [
    {
      name: "llm.stream.delta",
      data: { stream_id: "a", kind: "content", snapshot: "part" },
    },
    {
      name: "llm.stream.delta",
      data: { stream_id: "a", kind: "content", snapshot: "partial" },
    },
    {
      name: "llm.stream.interrupted",
      data: { stream_id: "a", partial: { content: "partial" } },
    },
  ];
  assert.deepEqual(replayStream(events), [
    { content: "partial", reasoning: "", complete: false },
  ]);
  assert.match(
    renderMarkdown('```js\nconst x = "<script>";'),
    /&lt;script&gt;/,
  );
});
