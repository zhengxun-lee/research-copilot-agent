import { mountModelSettings } from "./components/model-settings.js";
import { mountDebugger } from "./components/debugger.js";
import { mountContextPanel } from "./components/context-panel.js";
import { api, fetchJson } from "./lib/api.js";
import { escapeHtml as esc } from "./lib/markdown.js";
import { hydrateIcons, icon } from "./components/icons.js";
import { mountGraph } from "./components/graph.js";
import { RuntimeStore } from "./lib/runtime-store.js";
import { mountEffects } from "./lib/effects.js";
import { updateExecutionTimeline, executionEventNames } from "./lib/execution-timeline.js";

const $ = (id) => document.getElementById(id);
const viewNames = {
  workspace: "研究工作台",
  knowledge: "知识库",
  settings: "设置",
  overview: "关于 Research Copilot",
};
const empty = (title, description, glyph = "layers") =>
  `<div class="inspector-empty">${icon(glyph)}<strong>${esc(title)}</strong>${description ? `<p>${esc(description)}</p>` : ""}</div>`;
const date = (value) =>
  new Date(value * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
export function mountWorkspace(bridge) {
  mountModelSettings();
  mountContextPanel();
  mountDebugger();
  hydrateIcons();
  mountEffects();
  const runtime = new RuntimeStore();
  let retrievalConfig = null;
  let selectedRetrieval = $("composerRetrieval").value;
  let currentView = "overview",
    knowledge = null,
    commands = [],
    commandIndex = 0;
  const graph = mountGraph($("executionGraph"), {
    onSelect: (id) => setInspector(id === "tools" ? "retrieval" : "runtime"),
  });
  mountGraph($("architectureGraph"), { architecture: true });
  graph({ state: "idle", running: false });
  const navigate = (view) => {
    location.hash = view;
  };
  function route() {
    let hash = location.hash.slice(1);
    if (["playground", "retrieval", "traces"].includes(hash)) {
      window.history.replaceState(null, "", "#workspace");
      hash = "workspace";
    }
    if (hash === "architecture") {
      navigate("overview");
      requestAnimationFrame(() =>
        $("architecture").scrollIntoView({ behavior: "smooth" }),
      );
      return;
    }
    currentView = Object.hasOwn(viewNames, hash) ? hash : "overview";
    for (const section of document.querySelectorAll("[data-view]"))
      section.hidden = section.dataset.view !== currentView;
    for (const link of document.querySelectorAll("[data-view-link]")) {
      const active = link.dataset.viewLink === currentView;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    document.body.classList.toggle("landing-mode", currentView === "overview");
    document.querySelector(".context-root").textContent =
      currentView === "overview" ? "Research Copilot" : "Workspace";
    $("toggleInspector").hidden = currentView !== "workspace";
    $("viewTitle").textContent = viewNames[currentView];
    document.title = `${viewNames[currentView]} · Research Copilot`;
    const navigatorOpen =
      currentView !== "overview" &&
      matchMedia("(min-width:721px)").matches &&
      !document.body.classList.contains("nav-collapsed");
    document.body.classList.toggle("sidebar-open", navigatorOpen);
    $("menuButton").setAttribute("aria-expanded", String(navigatorOpen));
    if (currentView === "knowledge") {
      renderDocuments();
    }
  }
  addEventListener("hashchange", route);
  route();
  document
    .querySelectorAll("[data-inspector-tab]")
    .forEach((button) =>
      button.addEventListener("click", () =>
        setInspector(button.dataset.inspectorTab),
      ),
    );
  function setInspector(tab) {
    document.querySelectorAll("[data-inspector-tab]").forEach((button) => {
      const active = button.dataset.inspectorTab === tab;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    });
    document
      .querySelectorAll("[data-inspector-panel]")
      .forEach(
        (panel) => (panel.hidden = panel.dataset.inspectorPanel !== tab),
      );
  }
  setInspector("trace");
  document
    .querySelector(".inspector-tabs")
    .addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...document.querySelectorAll("[data-inspector-tab]")];
      const index = tabs.indexOf(document.activeElement);
      const next =
        tabs[
          (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) %
            tabs.length
        ];
      next.click();
      next.focus();
    });
  $("toggleInspector").addEventListener("click", () => {
    const details = [...document.querySelectorAll(".answer-execution")].at(-1);
    if (details) {
      details.open = !details.open;
      $("toggleInspector").setAttribute("aria-expanded", String(details.open));
      details.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    }
  });
  function sessionChanged() {
    const session = bridge.getSession();
    $("activeSessionTitle").textContent = session.messages.length
      ? session.title
      : "Untitled research";
    $("sessionCount").textContent = String(bridge.getSessions().length);
  }
  document.addEventListener("research:session", sessionChanged);
  sessionChanged();
  $("newChatButton").addEventListener("click", () => {
    navigate("workspace");
  });
  document.addEventListener("research:knowledge", (event) => {
    knowledge = event.detail;
    renderKnowledge();
  });
  const retrievalNotice = $("retrievalNotice");
  const showRetrievalNotice = (message) => {
    $("retrievalNoticeText").textContent = message;
    if (!retrievalNotice.open) retrievalNotice.showModal();
  };
  $("closeRetrievalNotice").onclick = () => retrievalNotice.close();
  retrievalNotice.addEventListener("close", () => $("composerRetrieval").focus());
  $("composerRetrieval").addEventListener("change", (event) => {
    const selector = event.target;
    if (selector.value === "hybrid" && !retrievalConfig?.hybrid_available) {
      selector.value = selectedRetrieval;
      showRetrievalNotice(retrievalConfig?.hybrid_unavailable_reason || "正在读取检索配置，请稍后重试");
      return;
    }
    selectedRetrieval = selector.value;
    selector.dataset.initialized = "true";
  });
  function renderKnowledge() {
    if (!knowledge) return;
    $("navDocCount").textContent = String(knowledge.document_count || 0);
    const selector = $("composerRetrieval");
    if (!selector.dataset.initialized) {
      if (knowledge.retrieval_mode !== "hybrid" && [...selector.options].some((option) => option.value === knowledge.retrieval_mode))
        selector.value = knowledge.retrieval_mode;
      selectedRetrieval = selector.value;
      selector.dataset.initialized = "true";
    }
    $("footerMode").textContent =
      `${knowledge.retrieval_mode || "—"} retrieval`;
    renderDocuments();
  }
  function renderDocuments() {
    if (!knowledge) return;
    const query = $("documentFilter").value.trim().toLowerCase();
    const documents = (knowledge.documents || []).filter((doc) =>
      (doc.title || "").toLowerCase().includes(query),
    );
    if (!documents.length) {
      $("knowledgeDocuments").innerHTML = empty(
        knowledge.document_count ? "没有匹配的文档" : "尚未导入文档",
        knowledge.error || "",
        "library",
      );
      return;
    }
    $("knowledgeDocuments").innerHTML =
      `<div class="document-collection">${documents.map((doc, index) => `<article class="document-item "><div class="document-title">${icon("file")}<span><strong>${esc(doc.title || doc.doc_id)}</strong><small>${doc.page_count} 页</small></span></div><button type="button" class="delete-document" data-delete-document="${index}" aria-label="删除 ${esc(doc.title || doc.doc_id)}">删除</button></article>`).join("")}</div>`;
    $("knowledgeDocuments")
      .querySelectorAll("[data-delete-document]")
      .forEach((button) => {
        button.addEventListener("click", async () => {
          const doc = documents[Number(button.dataset.deleteDocument)];
          if (
            !window.confirm(
              `从知识库删除“${doc.title || doc.doc_id}”？其片段索引与上传副本将一并移除。`,
            )
          )
            return;
          button.disabled = true;
          button.textContent = "删除中…";
          try {
            const result = await fetchJson("/api/kb/delete", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ doc_id: doc.doc_id }),
            });
            await bridge.reloadKnowledge?.();
            if (result.file_cleanup_pending)
              window.alert("文档索引已删除，上传副本因文件权限无法清理。");
          } catch (error) {
            window.alert(error.message);
            button.disabled = false;
            button.textContent = "删除";
          }
        });
      });
  }
  $("documentFilter").addEventListener("input", renderDocuments);
  $("refreshKnowledge").addEventListener("click", async () => {
    try {
      knowledge = await api.knowledge();
      renderKnowledge();
      bridge.reloadKnowledge?.();
      bridge.toast("已刷新本地知识库");
    } catch (error) {
      bridge.toast(error.message);
    }
  });
  document.addEventListener("research:runtime", (event) => {
    const { status, session } = event.detail;
    const run = runtime.ingest(status, session);
    sessionChanged();
    graph(status, run?.events || []);
    $("runtimeState").dataset.state = status.state;
    $("flowStatus").textContent = status.running
      ? "Executing"
      : status.state === "idle"
        ? "Awaiting task"
        : status.state;
    $("footerTask").textContent = status.run_id
      ? `${status.state} · ${status.run_id.slice(0, 10)}`
      : "No active task";
    if (run) {
      $("eventCount").textContent = `${run.events.filter((e) => executionEventNames.has(e.name)).length} 个步骤`;
      $("traceEmpty").hidden = true;
      renderTimeline(run);
      renderRetrieval(run);
      renderMeters(status.budget);
    } else {
      $("runtimeEvents").replaceChildren();
      $("traceEmpty").hidden = false;
      $("eventCount").textContent = "0 events";
    }
  });
  function renderTimeline(run) {
    updateExecutionTimeline($("runtimeEvents"), run.events);
  }
  function renderRetrieval(run) {
    const calls = run.events.filter(
      (e) => e.name === "tool.completed" && e.data.name === "search_knowledge",
    );
    $("retrievalInspector").classList.remove("inspector-empty");
    $("retrievalInspector").innerHTML = calls.length
      ? calls
          .slice(-3)
          .map(
            (e) =>
              `<article class="result-card"><header>search_knowledge · ${date(e.timestamp)}</header><h3>Tool observation</h3><p>${esc(e.data.result || "无返回文本")}</p></article>`,
          )
          .join("")
      : empty("暂无检索记录", "", "search");
  }
  function renderMeters(budget) {
    if (!budget) return;
    $("runtimeMeters").innerHTML = [
      "steps",
      "llm_calls",
      "tool_calls",
      "tokens",
      "seconds",
      "cost",
    ]
      .filter((key) => budget.limits["max_" + key] != null)
      .map((key) => {
        const limit = budget.limits["max_" + key],
          value = budget.used[key] || 0;
        return `<div class="budget-meter"><div><span>${key}</span><span>${typeof value === "number" ? Number(value.toFixed(4)) : value} / ${limit}</span></div><meter min="0" max="${Math.max(1, limit)}" value="${Math.min(limit, value)}" aria-label="${key} budget"></meter></div>`;
      })
      .join("");
  }
  const budgetForm = $("budgetForm");
  try {
    const saved = JSON.parse(localStorage.getItem("research-budget") || "null");
    if (saved)
      for (const input of budgetForm.querySelectorAll("[name]"))
        if (Object.hasOwn(saved, input.name)) input.value = saved[input.name];
  } catch {}
  $("saveBudget").onclick = () => {
    if (!budgetForm.reportValidity()) return;
    const values = Object.fromEntries(new FormData(budgetForm));
    if (
      values.max_cost !== "" &&
      (!(Number(values.input_price_per_million) > 0) ||
        !(Number(values.output_price_per_million) > 0))
    ) {
      bridge.toast("设置费用上限时，请填写正数输入和输出单价");
      return;
    }
    try {
      localStorage.setItem("research-budget", JSON.stringify(values));
      bridge.toast("预算偏好已保存，下次启动任务生效");
    } catch {
      bridge.toast("浏览器无法保存偏好");
    }
  };
  async function loadConfig() {
    try {
      const config = await api.config();
      retrievalConfig = config.retrieval;
      $("composerRouting").hidden = !config.agent?.router_enabled;
      if ($("composerRetrieval").value === "hybrid" && !retrievalConfig?.hybrid_available) {
        $("composerRetrieval").value = "keyword";
        selectedRetrieval = "keyword";
        showRetrievalNotice(retrievalConfig?.hybrid_unavailable_reason || "混合检索尚未配置");
      }
      $("footerConnection").classList.add("connected");
      $("footerStatus").textContent = "Connected to local runtime";
    } catch (error) {
      $("footerStatus").textContent = "Local runtime unavailable";
    }
  }
  document.addEventListener("research:models-saved", loadConfig);
  loadConfig();
  api
    .knowledge()
    .then((data) => {
      knowledge = data;
      renderKnowledge();
    })
    .catch((error) => {
      $("knowledgeDocuments").innerHTML = empty("知识库不可用", error.message);
    });
  // Native dialog supplies focus containment and Escape behavior.
  const palette = $("commandPalette"),
    search = $("commandSearch");
  let returnFocus = null;
  function openCommands() {
    returnFocus = document.activeElement;
    if (!palette.open) palette.showModal();
    search.value = "";
    renderCommands();
    search.focus();
  }
  function closeCommands() {
    palette.close();
    returnFocus?.focus();
  }
  function renderCommands() {
    const query = search.value.toLowerCase();
    commands = [
      ...Object.entries(viewNames).map(([id, name]) => ({
        name,
        kind: "Go to view",
        run: () => navigate(id),
      })),
      {
        name: "New research session",
        kind: "Action",
        run: () => {
          bridge.newSession();
          navigate("workspace");
        },
      },
      ...bridge.getSessions().map((session) => ({
        name: session.title,
        kind: "Research session",
        run: () => {
          bridge.selectSession(session.id);
          navigate("workspace");
        },
      })),
    ].filter((item) => item.name.toLowerCase().includes(query));
    commandIndex = 0;
    drawCommands();
  }
  function drawCommands() {
    $("commandResults").innerHTML =
      commands
        .map(
          (item, index) =>
            `<button role="option" aria-selected="${index === commandIndex}" id="command-${index}" data-command="${index}">${icon("terminal")}${esc(item.name)}<small>${item.kind}</small></button>`,
        )
        .join("") || '<p class="inspector-note">没有匹配的命令</p>';
    search.setAttribute("aria-controls", "commandResults");
    search.setAttribute(
      "aria-activedescendant",
      commands.length ? `command-${commandIndex}` : "",
    );
    $("commandResults")
      .querySelectorAll("[data-command]")
      .forEach(
        (button) =>
          (button.onclick = () =>
            executeCommand(Number(button.dataset.command))),
      );
  }
  function executeCommand(index) {
    const command = commands[index];
    if (!command) return;
    closeCommands();
    command.run();
  }
  search.addEventListener("input", renderCommands);
  search.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (commands.length) {
        commandIndex =
          (commandIndex +
            (event.key === "ArrowDown" ? 1 : commands.length - 1)) %
          commands.length;
        drawCommands();
        $("command-" + commandIndex)?.scrollIntoView({ block: "nearest" });
      }
    }
    if (event.key === "Enter") {
      event.preventDefault();
      executeCommand(commandIndex);
    }
  });
  document
    .querySelectorAll("[data-command-open]")
    .forEach((button) => (button.onclick = openCommands));
  palette.addEventListener("click", (event) => {
    if (event.target === palette) closeCommands();
  });
  palette.addEventListener("close", () => returnFocus?.focus());
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openCommands();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") {
      event.preventDefault();
      bridge.newSession();
      navigate("workspace");
    }
    if (event.key === "Escape")
      document.body.classList.remove("inspector-mobile-open");
  });
  return { navigate, runtime };
}
