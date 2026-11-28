// Cumulative server snapshots make duplicate/reconnected SSE deliveries idempotent.
export function applyStreamSnapshot(message, snapshot) {
  if (!message || !snapshot?.stream_id) return false;
  if (
    message.streamId === snapshot.stream_id &&
    snapshot.sequence != null &&
    snapshot.sequence <= (message.streamSequence ?? -1)
  )
    return false;
  const changed =
    message.streamId !== snapshot.stream_id ||
    message.content !== snapshot.content ||
    message.reasoning !== snapshot.reasoning ||
    message.streamComplete !== snapshot.complete;
  message.streamId = snapshot.stream_id;
  message.streamSequence = snapshot.sequence ?? message.streamSequence;
  message.content = snapshot.content || "";
  message.reasoning = snapshot.reasoning || "";
  message.streamComplete = Boolean(snapshot.complete);
  message.model = snapshot.model || message.model;
  return changed;
}

export function replayStream(events) {
  const streams = new Map();
  for (const event of events) {
    const data = event.data || {};
    if (!data.stream_id) continue;
    const state = streams.get(data.stream_id) || {
      content: "",
      reasoning: "",
      complete: false,
    };
    if (event.name === "llm.stream.delta")
      state[data.kind] = data.snapshot || "";
    if (event.name === "llm.stream.accepted")
      Object.assign(state, data.output, { complete: true });
    if (event.name === "llm.stream.interrupted")
      Object.assign(state, data.partial, { complete: false });
    streams.set(data.stream_id, state);
  }
  return [...streams.values()];
}
