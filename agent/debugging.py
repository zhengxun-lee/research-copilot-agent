"""Explicit branch creation from private safe snapshots. Offline replay never calls this."""

from copy import deepcopy
import json
from uuid import uuid4
import re

from agent.runtime import AbortExecution


def fork_checkpoint(agent, store, source_run, checkpoint_id, arguments=None, model=None, pressure=None):
    if agent.last_run is not None:
        raise ValueError("Branch requires a fresh Agent")
    if model not in {None, "simple", "complex"}:
        raise ValueError("Model must be simple or complex")
    if pressure is not None and not isinstance(pressure, bool):
        raise ValueError("Invalid context strategy")
    data = deepcopy(store.snapshot(source_run, checkpoint_id))
    if data["task"]["phase"] not in {"route", "think", "llm", "tools", "final"}:
        raise ValueError("Cannot branch an in-flight external operation")
    if arguments is not None:
        if not isinstance(arguments, dict) or data["task"]["phase"] != "tools":
            raise ValueError("Parameter edits require a pending tool at a safe boundary")
        task = data["task"]
        index = task["index"]
        if index >= len(task["calls"]):
            raise ValueError("No pending tool to edit")
        call = task["calls"][index]
        if agent._side_effectful(call["name"]):
            raise ValueError("Side-effectful tools cannot be branched")
        call["arguments"] = arguments
        call["raw_arguments"] = json.dumps(arguments)
        call.pop("prepared", None)
        call.pop("parse_error", None)
        task.pop("approval", None)
        for message in reversed(data["messages"]):
            matching = next((stored for stored in message.get("tool_calls", []) if stored["id"] == call["id"]), None)
            if matching is not None:
                matching["function"]["arguments"] = call["raw_arguments"]
                break
    new_id = uuid4().hex
    data["context"]["run_id"] = new_id
    data["task"]["debug_read_only"] = True
    data["task"]["branch_parent"] = {"run_id": source_run, "checkpoint_id": checkpoint_id}
    data["context"]["state"] = "paused"
    data["task"]["resume_state"] = {
        "route": "routing",
        "think": "thinking",
        "llm": "thinking",
        "tools": "executing",
        "final": "thinking",
    }[data["task"]["phase"]]
    data["task"].pop("suspended_at", None)
    data["trace_identity"] = agent.trace.identity(new_id)
    cutoff = data.get("debug_snapshot_time")
    if not isinstance(cutoff, (int, float)):
        raise ValueError("Historical context cutoff is unavailable for this checkpoint")
    if data.get("context_engine"):
        scope = uuid4().hex
        agent.memory.store.clone_scope(data["context_engine"]["scope"], scope, before=cutoff)
        for ref in re.findall(r"original offloaded: context:([a-f0-9]{24})", json.dumps(data["messages"])):
            agent.memory.store.get(scope, ref)
        data["context_engine"]["scope"] = scope
        if pressure is not None:
            data["context_engine"]["pressure"] = pressure
    if model:
        data["task"]["model_route"] = model
    data["task"].pop("approval", None)
    if not agent.checkpoint_store:
        raise ValueError("Branch execution requires CheckpointStore")
    agent.checkpoint_store.save(new_id, data)
    agent.restore(new_id)
    if model:
        agent.last_route_decision = agent.model_router._decision(model, 1.0, "debug branch override")

    # Every future invocation, including a model-requested different tool, is checked.
    def read_only_policy(context, payload):
        if agent._side_effectful(payload["name"]):
            raise AbortExecution("Debug branches forbid side-effectful tools")
        return payload

    agent.hooks.register("tool.prepare", "before", read_only_policy)
    agent.hooks.register("tool", "before", read_only_policy)
    agent._task["debug_read_only"] = True
    agent._task["branch_parent"] = dict(run_id=source_run, checkpoint_id=checkpoint_id)
    agent._emit("run.started", branch=True)
    agent._emit(
        "trace.branch.created",
        source_run=source_run,
        checkpoint_id=checkpoint_id,
        model_override=model,
        context_pressure=pressure,
        read_only=True,
        inherited_budget={
            key: data["context"].get(key) for key in ("tokens", "cost", "llm_calls", "tool_calls", "steps")
        },
    )
    agent._save()
    return new_id
