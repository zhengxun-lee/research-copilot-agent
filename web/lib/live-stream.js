// Real SSE transport. Reconnection uses the browser's Last-Event-ID support.
export class LiveRuntime {
  constructor(onStatus) {
    this.onStatus = onStatus;
    this.sources = new Map();
    this.latest = new Map();
    this.arrivals = new Map();
  }
  follow(sessionId) {
    if (typeof EventSource === "undefined") return false;
    if (this.sources.has(sessionId)) return true;
    if (this.sources.size >= 3) this.stop(this.sources.keys().next().value);
    const source = new EventSource(
      "/api/events?session_id=" + encodeURIComponent(sessionId),
    );
    this.sources.set(sessionId, source);
    source.addEventListener("runtime", (event) => {
      try {
        const status = JSON.parse(event.data);
        const previous = this.latest.get(sessionId);
        if (
          previous?.run_id === status.run_id &&
          Number.isFinite(status.cursor) &&
          Number.isFinite(previous?.cursor) &&
          status.cursor < previous.cursor
        )
          return;
        this.latest.set(sessionId, status);
        this.arrivals.set(sessionId, Date.now());

        this.onStatus(sessionId, status);
      } catch (error) {
        console.error("Invalid runtime SSE frame", error);
      }
    });
    return true;
  }
  cached(sessionId) {
    return Date.now() - (this.arrivals.get(sessionId) || 0) < 3500
      ? this.latest.get(sessionId)
      : undefined;
  }
  stop(sessionId) {
    this.sources.get(sessionId)?.close();
    this.sources.delete(sessionId);
    this.latest.delete(sessionId);
    this.arrivals.delete(sessionId);
  }
  close() {
    for (const source of this.sources.values()) source.close();
    this.sources.clear();
  }
}
