// Projection of observed server events. No model thoughts, inferred scores or demo runs.
export class RuntimeStore {
  constructor() {
    this.runs = new Map();
    this.selected = null;
  }
  ingest(status, session) {
    if (!status.run_id) return null;
    let run = this.runs.get(status.run_id);
    if (!run) {
      run = {
        id: status.run_id,
        query:
          status.query ||
          session?.messages?.filter((m) => m.role === "user").at(-1)?.content ||
          "恢复的研究任务",
        events: [],
        seen: new Set(),
      };
      this.runs.set(run.id, run);
    }
    for (const event of status.events || []) {
      if (event.run_id === run.id && !run.seen.has(event.event_id)) {
        run.seen.add(event.event_id);
        run.events.push(event);
      }
    }
    if (run.events.length > 400) {
      run.events = run.events.slice(-400);
      run.seen = new Set(run.events.map((e) => e.event_id));
      run.truncated = true;
    }
    Object.assign(run, {
      state: status.state,
      model: status.model,
      route: status.route,
      budget: status.budget,
      result: status.result,
      error: status.error,
      gap: run.gap || status.gap,
    });
    while (this.runs.size > 30) this.runs.delete(this.runs.keys().next().value);
    this.selected = run.id;
    return run;
  }
  list() {
    return [...this.runs.values()].reverse();
  }
  export(id = this.selected) {
    const run = this.runs.get(id);
    if (!run) return null;
    const { seen, ...data } = run;
    return data;
  }
}
export function graphState(status, events) {
  const visited = new Set();
  for (const e of events) {
    if (e.name === "run.started") visited.add("query");
    if (e.name === "route.completed") visited.add("router");
    if (e.name === "llm.started" || e.name === "llm.completed")
      visited.add("llm");
    if (e.name === "tool.started" || e.name === "tool.completed")
      visited.add("tools");
    if (e.name === "run.finished" && e.state === "completed")
      visited.add("answer");
  }
  const active =
    {
      routing: "router",
      thinking: "llm",
      recovering: "llm",
      retrieving: "tools",
      executing: "tools",
      completed: "answer",
    }[status?.state] ||
    {
      route: "router",
      think: "llm",
      llm: "llm",
      tools: "tools",
      tool_inflight: "tools",
      final: "answer",
    }[status?.phase];
  return {
    visited,
    active,
    running: !!status?.running,
    failed: ["failed", "exhausted"].includes(status?.state),
  };
}
