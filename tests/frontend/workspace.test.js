import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { JSDOM, VirtualConsole } from "jsdom";

// DOM unit harness only. Production receives data exclusively from Python HTTP APIs.
test("all workspace views, command palette and task transport initialize without client errors", async () => {
  const errors = [];
  const console = new VirtualConsole();
  console.on("jsdomError", (e) => errors.push(e));
  const dom = new JSDOM(fs.readFileSync("web/index.html", "utf8"), {
    url: "http://localhost/",
    pretendToBeVisual: true,
    virtualConsole: console,
  });
  const w = dom.window;
  for (const key of [
    "window",
    "document",
    "localStorage",
    "CustomEvent",
    "Event",
    "KeyboardEvent",
    "HTMLElement",
    "location",
    "FormData",
  ])
    globalThis[key] = key === "window" ? w : w[key];
  Object.defineProperty(globalThis, "navigator", {
    value: w.navigator,
    configurable: true,
  });
  globalThis.addEventListener = w.addEventListener.bind(w);
  globalThis.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
  globalThis.requestAnimationFrame = () => 1;
  globalThis.cancelAnimationFrame = () => {};
  globalThis.IntersectionObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
  w.HTMLCanvasElement.prototype.getContext = () => null;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  w.HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const intervals = [];
  const originalInterval = globalThis.setInterval;
  globalThis.setInterval = (fn) => {
    intervals.push(fn);
    return intervals.length;
  };
  const calls = [];
  let hybridAvailable = false;
  let routerEnabled = false;
  globalThis.fetch = async (url, options = {}) => {
    calls.push([url, options]);
    let body = {};
    if (url === "/api/settings/models")
      body = {
        router_enabled: true,
        revision: 0,
        can_edit: true,
        profiles: Object.fromEntries(
          ["default", "simple", "complex", "embedding"].map((role) => [
            role,
            {
              model_name: "unit-" + role,
              base_url: "https://api.example.test/v1",
              key_configured: false,
              key_mode: "clear",
            },
          ]),
        ),
      };
    else if (url === "/api/config/public")
      body = {
        models: {
          simple: "unit-simple",
          complex: "unit-complex",
          embedding: "unit-embedding",
        },
        api_configured: false,
        retrieval: { mode: "keyword", embedding_enabled: hybridAvailable,
          hybrid_available: hybridAvailable, hybrid_unavailable_reason: "请先配置 Embedding API" },
        agent: { max_memory_turns: 10, router_enabled: routerEnabled },
      };
    else if (url === "/api/kb/stats")
      body = {
        exists: false,
        document_count: 0,
        chunk_count: 0,
        retrieval_mode: "keyword",
        documents: [],
      };
    else if (url === "/api/retrieval/search")
      body = { results: [], duration_ms: 2 };
    else if (url === "/api/tasks/start") body = { session_id: "unit-session" };
    else if (url.startsWith("/api/tasks/status"))
      body = {
        run_id: "unit-run",
        state: "completed",
        running: false,
        model: "unit-simple",
        route: "simple",
        result: "unit result",
        cursor: 1,
        events: [
          {
            event_id: "unit-event",
            run_id: "unit-run",
            timestamp: 1,
            name: "run.finished",
            state: "completed",
            data: {},
          },
        ],
        budget: {
          limits: {
            max_steps: 5,
            max_llm_calls: 20,
            max_tool_calls: 20,
            max_tokens: null,
            max_cost: null,
            max_seconds: 300,
          },
          used: {
            steps: 1,
            llm_calls: 1,
            tool_calls: 0,
            tokens: 0,
            cost: 0,
            seconds: 0.1,
            retries: 0,
            recoveries: 0,
          },
        },
      };
    if (url.startsWith("/api/traces?"))
      body = { runs: [{ run_id: "offline-unit", event_count: 2 }] };
    if (url.startsWith("/api/traces/detail"))
      body = {
        run_id: "offline-unit",
        checkpoints: [],
        metrics: {
          usage_responses: 0,
          missing_usage: 0,
          retries: 0,
          total_duration_ms: 1,
        },
        events: [
          {
            event_id: "offline-start",
            run_id: "offline-unit",
            run_sequence: 1,
            timestamp: 1,
            name: "run.started",
            state: "routing",
            data: {},
          },
          {
            event_id: "offline-request",
            run_id: "offline-unit",
            run_sequence: 2,
            timestamp: 1.001,
            name: "model.request",
            state: "thinking",
            data: { request: { messages: [] } },
          },
        ],
      };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    await import("../../web/app.js");
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(w.document.querySelector('[data-view="overview"]').hidden, false);
    assert.equal(w.document.querySelector('[data-view="workspace"]').hidden, true);
    w.location.hash = "workspace";
    await new Promise((resolve) => setTimeout(resolve, 5));
    assert.ok(w.document.querySelector(".empty-state h1"));
    const newChat = w.document.getElementById("newChatButton");
    assert.equal(newChat.querySelector("svg, kbd, [data-icon]"), null);
    assert.equal(w.document.querySelector('[data-view-link="workspace"] svg'), null);
    const initialSessions = w.document.querySelectorAll(".session-row").length;
    newChat.click();
    newChat.click();
    assert.equal(w.document.querySelectorAll(".session-row").length, initialSessions);
    // Native label activation must reach the file input without a JS .click proxy.
    const picker = w.document.getElementById("pdfUpload");
    let pickerClicks = 0;
    picker.addEventListener("click", () => pickerClicks++);
    w.document.getElementById("pdfUploadLabel").click();
    assert.equal(pickerClicks, 1);
    assert.equal(picker.hidden, false);
    assert.equal(picker.closest("label").id, "pdfUploadLabel");

    assert.equal(w.document.querySelectorAll("[data-view]").length, 4);
    for (const view of ["knowledge", "settings", "overview", "workspace"]) {
      w.location.hash = view;
      await new Promise((resolve) => setTimeout(resolve, 5));
      assert.equal(
        w.document.querySelector(`[data-view="${view}"]`).hidden,
        false,
      );
    }
    w.document.getElementById("openPdfImport").click();
    assert.equal(w.document.getElementById("pdfImportDialog").open, true);
    assert.ok(
      w.document
        .getElementById("pdfImportDialog")
        .contains(w.document.getElementById("pdfUpload")),
    );
    w.document.getElementById("closePdfImport").click();
    assert.equal(w.document.getElementById("pdfImportDialog").open, false);
    // All research uses the single composer; legacy retrieval links remain compatible.
    w.location.hash = "playground";
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(w.location.hash, "#workspace");
    assert.equal(w.document.getElementById("messages").hidden, false);
    assert.equal(w.document.querySelector(".composer-wrap").hidden, false);
    assert.equal(w.document.getElementById("retrievalForm"), null);
    assert.equal(w.document.querySelector("[data-workspace-mode]"), null);
    assert.equal(
      w.document.querySelector('[data-view-link="playground"]'),
      null,
    );
    assert.equal(w.document.querySelector("[data-command-open]"), null);
    assert.equal(w.document.getElementById("headerModel"), null);
    w.document.dispatchEvent(
      new w.KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
    );
    assert.equal(w.document.querySelector("#commandPalette").open, true);
    const search = w.document.querySelector("#commandSearch");
    search.value = "知识库";
    search.dispatchEvent(new w.Event("input"));
    assert.equal(w.document.querySelectorAll("[data-command]").length, 1);
    search.dispatchEvent(
      new w.KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    );
    await new Promise((resolve) => setTimeout(resolve, 5));
    assert.equal(w.location.hash, "#knowledge");
    w.location.hash = "workspace";
    await new Promise((resolve) => setTimeout(resolve, 5));
    const input = w.document.querySelector("#messageInput");
    const retrieval = w.document.getElementById("composerRetrieval");
    assert.deepEqual([...retrieval.options].map((o) => o.value), ["keyword", "semantic", "hybrid"]);
    assert.equal(w.document.getElementById("composerRouting").hidden, true);
    retrieval.value = "hybrid";
    retrieval.dispatchEvent(new w.Event("change"));
    assert.equal(retrieval.value, "keyword");
    assert.equal(w.document.getElementById("retrievalNotice").open, true);
    assert.equal(w.document.getElementById("retrievalNoticeText").textContent, "请先配置 Embedding API");
    w.document.getElementById("closeRetrievalNotice").click();
    assert.equal(w.document.getElementById("retrievalNotice").open, false);
    hybridAvailable = true;
    routerEnabled = true;
    w.document.dispatchEvent(new w.CustomEvent("research:models-saved"));
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(w.document.getElementById("composerRouting").hidden, false);
    retrieval.value = "hybrid";
    retrieval.dispatchEvent(new w.Event("change"));
    input.value = "unit test request";
    w.document
      .querySelector("#chatForm")
      .dispatchEvent(new w.Event("submit", { cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 35));
    assert.ok(calls.some(([url]) => url === "/api/tasks/start"));
    const startRequest = calls.find(([url]) => url === "/api/tasks/start");
    assert.equal(JSON.parse(startRequest[1].body).retrieval_mode, "hybrid");
    assert.ok(
      w.document.querySelector("#messages").textContent.includes("unit result"),
    );
    const countBeforeNew = w.document.querySelectorAll(".session-row").length;
    newChat.click();
    assert.equal(w.document.querySelectorAll(".session-row").length, countBeforeNew + 1);
    const blankSessionId = JSON.parse(w.localStorage.getItem("research-copilot-web-state")).activeSessionId;
    // Return to the answered conversation, then reuse the existing blank one.
    w.document.querySelectorAll(".session-item")[1].click();
    newChat.click();
    assert.equal(w.document.querySelectorAll(".session-row").length, countBeforeNew + 1);
    assert.equal(JSON.parse(w.localStorage.getItem("research-copilot-web-state")).activeSessionId, blankSessionId);
    w.document.querySelectorAll(".session-item")[1].click();
    assert.equal(
      w.document.querySelector("#runtimeState").textContent,
      "completed",
    );
    const executionDetails = w.document.querySelector(".answer-execution");
    assert.ok(executionDetails, "answer owns its execution details");
    assert.equal(
      executionDetails.open,
      false,
      "details stay folded during a real task transport cycle",
    );
    assert.ok(
      executionDetails.contains(w.document.getElementById("agentInspector")),
    );
    assert.equal(
      w.document.getElementById("taskStatusText").textContent,
      "已完成",
    );
    w.document.getElementById("toggleInspector").click();
    assert.equal(executionDetails.open, true);
    assert.equal(errors.length, 0, errors.map((e) => e.message).join("\n"));
    const contextEvent = {
      event_id: "context-unit",
      run_id: "unit-run",
      timestamp: 1,
      name: "context.assembled",
      state: "thinking",
      data: {
        window: 4000,
        used: 800,
        reserved: 500,
        categories: { system: 100, history: 700, output_reserve: 500 },
        fragments: [],
      },
    };
    document.dispatchEvent(
      new w.CustomEvent("research:runtime", {
        detail: {
          status: {
            run_id: "unit-run",
            state: "thinking",
            running: true,
            events: [contextEvent],
          },
          session: { messages: [] },
        },
      }),
    );
    document.querySelector('[data-inspector-tab="context"]').click();
    assert.equal(
      document.querySelector('[data-inspector-panel="context"]').hidden,
      false,
    );
    assert.ok(
      document.querySelector("#contextComposition").textContent.includes("800"),
    );
    assert.equal(document.querySelectorAll(".context-stack span").length, 3);
    // Removed history UI must not issue background history queries.
    const writesBefore = calls.filter(
      ([, options]) => options.method === "POST",
    ).length;
    w.location.hash = "traces";
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(w.location.hash, "#workspace");
    assert.equal(document.querySelector('[data-view="traces"]'), null);
    assert.equal(document.querySelector('[data-view-link="traces"]'), null);
    assert.equal(document.getElementById("replayWorkspace"), null);
    assert.equal(
      calls.filter(([, options]) => options.method === "POST").length,
      writesBefore,
    );
    assert.equal(
      calls.some(([url]) => url.startsWith("/api/traces")),
      false,
    );
  } finally {
    globalThis.setInterval = originalInterval;
    dom.window.close();
  }
});
