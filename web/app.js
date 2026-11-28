import { updateStreamArticle } from "./lib/stream-dom.js";
import { applyStreamSnapshot } from "./lib/stream-state.js";
import { LiveRuntime } from "./lib/live-stream.js";
import { fetchJson, ApiError } from "./lib/api.js";
import { escapeHtml, renderMarkdown } from "./lib/markdown.js";
import { mountWorkspace } from "./workspace.js";
import { renderExecutionTimeline, executionEventNames } from "./lib/execution-timeline.js";
const STORAGE_KEY = "research-copilot-web-state";
const STORAGE_VERSION = 1;
const MAX_SESSIONS = 30;
const MAX_MESSAGES_PER_SESSION = 80;
const COMPACT_MESSAGES_PER_SESSION = 24;
const QUICK_REQUEST_TIMEOUT_MS = 15000;
const AUTO_SCROLL_THRESHOLD = 80;
const IS_MAC = navigator.platform.toLowerCase().includes("mac");

const sessionList = document.querySelector("#sessionList");
const messagesEl = document.querySelector("#messages");
const chatForm = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const newChatButton = document.querySelector("#newChatButton");
const menuButton = document.querySelector("#menuButton");
const shortcutHint = document.querySelector(".shortcut-hint");

let state = loadState();
let isSending = false;
let lastRenderedSessionId = null;
const feedbackTimers = new WeakMap();

if (shortcutHint) {
  shortcutHint.textContent = IS_MAC ? "⌘K" : "Ctrl K";
}

function createLocalId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function createLocalSession() {
  const id = createLocalId();
  return {
    id,
    serverId: null,
    runId: null,
    title: "新对话",
    messages: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function toFiniteNumber(value, fallback) {
  return Number.isFinite(value) ? value : fallback;
}

function normalizeMessage(message) {
  if (!isPlainObject(message)) {
    return null;
  }
  if (message.role !== "user" && message.role !== "assistant") {
    return null;
  }
  if (message.loading && !message.content) {
    return null;
  }

  const normalized = {
    role: message.role,
    content:
      typeof message.content === "string"
        ? message.content
        : String(message.content || ""),
  };
  if (message.model) {
    normalized.model = String(message.model);
  }
  if (message.route) {
    normalized.route = String(message.route);
  }
  if (message.error) {
    normalized.error = true;
  }
  if (message.reasoning) normalized.reasoning = String(message.reasoning);
  if (message.incomplete) normalized.incomplete = true;
  if (isPlainObject(message.execution)) {
    normalized.execution = {
      run_id: message.execution.run_id,
      state: message.execution.state,
      model: message.execution.model,
      error: message.execution.error,
      budget: message.execution.budget,
      events: (message.execution.events || []).filter((event) => executionEventNames.has(event.name)).slice(-160).map((event) => ({
        event_id: event.event_id,
        name: event.name,
        timestamp: event.timestamp,
        state: event.state,
        data: event.data,
      })),
    };
  }
  return normalized;
}

function normalizeSession(session) {
  if (!isPlainObject(session)) {
    return null;
  }

  const now = Date.now();
  const messages = Array.isArray(session.messages)
    ? session.messages
        .map(normalizeMessage)
        .filter(Boolean)
        .slice(-MAX_MESSAGES_PER_SESSION)
    : [];

  return {
    id:
      typeof session.id === "string" && session.id
        ? session.id
        : createLocalId(),
    serverId:
      typeof session.serverId === "string" && session.serverId
        ? session.serverId
        : null,
    runId: typeof session.runId === "string" ? session.runId : null,
    title:
      String(session.title || "新对话")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 80) || "新对话",
    messages,
    createdAt: toFiniteNumber(session.createdAt, now),
    updatedAt: toFiniteNumber(session.updatedAt, now),
  };
}

function normalizeState(saved) {
  if (!isPlainObject(saved) || !Array.isArray(saved.sessions)) {
    return null;
  }

  const seenSessionIds = new Set();
  const sessions = [];
  for (const rawSession of saved.sessions) {
    const session = normalizeSession(rawSession);
    if (!session || seenSessionIds.has(session.id)) {
      continue;
    }
    seenSessionIds.add(session.id);
    sessions.push(session);
    if (sessions.length >= MAX_SESSIONS) {
      break;
    }
  }

  if (!sessions.length) {
    return null;
  }

  const activeSessionId = sessions.some(
    (session) => session.id === saved.activeSessionId,
  )
    ? saved.activeSessionId
    : sessions[0].id;

  return {
    version: STORAGE_VERSION,
    activeSessionId,
    sessions,
  };
}

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    const normalized = normalizeState(saved);
    if (normalized) {
      return normalized;
    }
    removeStoredState();
  } catch (_error) {
    removeStoredState();
  }
  const session = createLocalSession();
  return {
    version: STORAGE_VERSION,
    activeSessionId: session.id,
    sessions: [session],
  };
}

function removeStoredState() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (_error) {
    // Ignore unavailable storage; the in-memory session still works.
  }
}

function createPersistableState(
  maxMessagesPerSession = MAX_MESSAGES_PER_SESSION,
) {
  if (!state.sessions.length) {
    const session = createLocalSession();
    state.sessions.push(session);
    state.activeSessionId = session.id;
  }

  const sessions = [...state.sessions];
  const activeIndex = sessions.findIndex(
    (session) => session.id === state.activeSessionId,
  );
  if (activeIndex >= MAX_SESSIONS) {
    const [activeSession] = sessions.splice(activeIndex, 1);
    sessions.unshift(activeSession);
  }

  const prunedSessions = sessions.slice(0, MAX_SESSIONS).map((session) => ({
    id: session.id,
    serverId: session.serverId || null,
    runId: session.runId || null,
    title: session.title || "新对话",
    messages: (session.messages || [])
      .map(normalizeMessage)
      .filter(Boolean)
      .slice(-maxMessagesPerSession),
    createdAt: session.createdAt,
    updatedAt: session.updatedAt,
  }));

  const activeSessionId = prunedSessions.some(
    (session) => session.id === state.activeSessionId,
  )
    ? state.activeSessionId
    : prunedSessions[0]?.id;

  return {
    version: STORAGE_VERSION,
    activeSessionId,
    sessions: prunedSessions,
  };
}

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(createPersistableState()));
  } catch (error) {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(createPersistableState(COMPACT_MESSAGES_PER_SESSION)),
      );
    } catch (_retryError) {
      console.warn("Unable to persist chat state.", error);
    }
  }
}

function getActiveSession() {
  let session = state.sessions.find(
    (item) => item.id === state.activeSessionId,
  );
  if (!session) {
    session = createLocalSession();
    state.sessions.unshift(session);
    state.activeSessionId = session.id;
  }
  return session;
}

function pruneSessionsInMemory() {
  if (state.sessions.length <= MAX_SESSIONS) {
    return;
  }

  const activeSession = state.sessions.find(
    (session) => session.id === state.activeSessionId,
  );
  const pruned = state.sessions.slice(0, MAX_SESSIONS);
  if (
    activeSession &&
    !pruned.some((session) => session.id === activeSession.id)
  ) {
    pruned[MAX_SESSIONS - 1] = activeSession;
  }
  state.sessions = pruned;
}

function pruneMessagesInMemory(session) {
  if (session.messages.length > MAX_MESSAGES_PER_SESSION) {
    session.messages = session.messages.slice(-MAX_MESSAGES_PER_SESSION);
  }
}

function setActiveSession(sessionId) {
  state.activeSessionId = sessionId;
  saveState();
  render();
}

function startNewChat() {
  const emptySession = state.sessions.find((session) => !session.messages.length);
  const session = emptySession || createLocalSession();
  if (!emptySession) state.sessions.unshift(session);
  state.activeSessionId = session.id;
  pruneSessionsInMemory();
  saveState();
  render();
  if (matchMedia("(max-width:720px)").matches) setSidebarOpen(false);
  input.focus();
}

async function deleteSession(sessionId) {
  const session = state.sessions.find((item) => item.id === sessionId);
  if (!session) return;
  if (session.serverId) {
    try {
      await fetchJson("/api/session/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.serverId }),
        timeoutMs: QUICK_REQUEST_TIMEOUT_MS,
      });
    } catch (error) {
      showToast(error.message);
      return;
    }
  }
  const index = state.sessions.findIndex((item) => item.id === sessionId);
  if (index < 0) return;
  state.sessions.splice(index, 1);
  if (state.activeSessionId === sessionId) {
    if (!state.sessions.length) state.sessions.push(createLocalSession());
    state.activeSessionId =
      state.sessions[Math.min(index, state.sessions.length - 1)].id;
  }
  saveState();
  render();
}

function titleFromMessage(message) {
  const compact = message.replace(/\s+/g, " ").trim();
  return compact.length > 34
    ? `${compact.slice(0, 34)}...`
    : compact || "新对话";
}

function formatRelativeTime(timestamp) {
  const time = Number(timestamp);
  if (!Number.isFinite(time)) {
    return "刚刚";
  }
  const elapsed = Date.now() - time;
  if (elapsed < 60_000) {
    return "刚刚";
  }
  if (elapsed < 3_600_000) {
    return `${Math.floor(elapsed / 60_000)} 分钟前`;
  }
  if (elapsed < 86_400_000) {
    return `${Math.floor(elapsed / 3_600_000)} 小时前`;
  }
  if (elapsed < 604_800_000) {
    return `${Math.floor(elapsed / 86_400_000)} 天前`;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(new Date(time));
}

function formatSessionMeta(session) {
  const messageCount = Array.isArray(session.messages)
    ? session.messages.length
    : 0;
  const messageText = messageCount ? `${messageCount} 条消息` : "空对话";
  return `${messageText} · ${formatRelativeTime(session.updatedAt || session.createdAt)}`;
}

function render() {
  renderSessions();
  renderMessages();
  autoResizeInput();
  document.dispatchEvent(
    new CustomEvent("research:session", { detail: getActiveSession() }),
  );
}

function renderSessions() {
  const fragment = document.createDocumentFragment();
  for (const session of state.sessions) {
    const row = document.createElement("div");
    row.className = `session-row${session.id === state.activeSessionId ? " active" : ""}`;

    const button = document.createElement("button");
    button.className = "session-item";
    button.type = "button";
    if (session.id === state.activeSessionId) {
      button.setAttribute("aria-current", "page");
    }
    button.title = session.title;
    button.addEventListener("click", () => {
      setActiveSession(session.id);
      location.hash = "workspace";
      if (matchMedia("(max-width:720px)").matches) setSidebarOpen(false);
    });

    const icon = document.createElement("span");
    icon.className = "session-icon";
    icon.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 6.5A3.5 3.5 0 0 1 8.5 3h7A3.5 3.5 0 0 1 19 6.5v5A3.5 3.5 0 0 1 15.5 15H12l-4.5 4v-4A3.5 3.5 0 0 1 5 11.5z"></path>
      </svg>
    `;

    const copy = document.createElement("span");
    copy.className = "session-copy";

    const title = document.createElement("span");
    title.className = "session-title";
    title.textContent = session.title;

    const meta = document.createElement("span");
    meta.className = "session-meta";
    meta.textContent = formatSessionMeta(session);

    copy.append(title, meta);
    button.append(icon, copy);

    const deleteButton = document.createElement("button");
    deleteButton.className = "session-delete-button";
    deleteButton.type = "button";
    deleteButton.title = "删除对话";
    deleteButton.setAttribute("aria-label", `删除对话：${session.title}`);
    deleteButton.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 6h18"></path>
        <path d="M8 6V4h8v2"></path>
        <path d="M19 6l-1 14H6L5 6"></path>
        <path d="M10 11v5"></path>
        <path d="M14 11v5"></path>
      </svg>
    `;
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteSession(session.id);
    });

    row.append(button, deleteButton);
    fragment.append(row);
  }
  sessionList.replaceChildren(fragment);
}

function renderMessages() {
  const inspector = document.getElementById("agentInspector");
  const previousDetails = inspector.closest("details");
  const wasOpen = previousDetails?.open || false;
  document.getElementById("inspectorParking").append(inspector);
  const session = getActiveSession();
  const sessionChanged = lastRenderedSessionId !== session.id;
  const distanceFromBottom =
    messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight;
  const shouldStickToBottom =
    sessionChanged || distanceFromBottom < AUTO_SCROLL_THRESHOLD;

  if (!session.messages.length) {
    messagesEl.replaceChildren(renderEmptyState());
    lastRenderedSessionId = session.id;
    return;
  }

  const list = document.createElement("div");
  list.className = "message-list";
  for (let index = 0; index < session.messages.length; index += 1) {
    const message = session.messages[index];
    const previousUser =
      index > 0 && session.messages[index - 1].role === "user"
        ? session.messages[index - 1]
        : null;
    const onRetry =
      message.error && previousUser
        ? () => retryFromMessage(previousUser.content)
        : null;
    const article = renderMessage(message, { onRetry });
    if (message.role === "assistant") {
      const details = document.createElement("details");
      details.className = "answer-execution";
      const summary = document.createElement("summary");
      summary.textContent = "执行详情";
      details.append(summary);
      if (index === session.messages.length - 1) {
        details.open =
          wasOpen &&
          !sessionChanged &&
          previousDetails?.dataset.answerIndex === String(index);
        details.dataset.answerIndex = String(index);
        details.append(inspector);
      } else {
        const record = document.createElement("ol");
        record.className = "runtime-events execution-record";
        const execution = message.execution;
        record.innerHTML = renderExecutionTimeline(execution?.events);
        details.append(record);
      }
      article.querySelector(".message-body")?.append(details);
    }
    list.append(article);
  }
  messagesEl.replaceChildren(list);
  lastRenderedSessionId = session.id;
  if (shouldStickToBottom) {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
}

function retryFromMessage(userContent) {
  // Drop everything from the failed user message onward so the retry starts
  // from a clean assistant response, then re-send the same content.
  const session = getActiveSession();
  const userIndex = session.messages.findIndex(
    (m) => m.role === "user" && m.content === userContent,
  );
  if (userIndex < 0) {
    return;
  }
  session.messages.splice(userIndex);
  session.updatedAt = Date.now();
  saveState();
  render();
  void sendMessage(userContent);
}

function renderEmptyState() {
  const wrapper = document.createElement("div");
  wrapper.className = "empty-state";

  const heading = document.createElement("h1");
  const art = document.createElement("img");
  art.className = "research-optics";
  art.src = "/assets/research-optics.png";
  art.alt = "";
  art.width = 1376;
  art.height = 768;
  wrapper.append(art);
  heading.textContent = "从一个研究问题开始";
  const grid = document.createElement("div");
  grid.className = "prompt-grid";
  const prompts = [
    "检索本地论文中关于注意力机制的证据",
    "比较 ReAct 与 Plan-and-Execute 的设计",
    "总结知识库中一篇论文的方法与局限",
    "计算 (2^10 + 512) / 3",
  ];

  for (const prompt of prompts) {
    const button = document.createElement("button");
    button.className = "prompt-chip";
    button.type = "button";
    button.innerHTML = `<span class="prompt-icon">${["⌕", "◇", "▤", "ƒ"][prompts.indexOf(prompt)]}</span><span>${escapeHtml(prompt)}</span>`;
    button.addEventListener("click", () => {
      input.value = prompt;
      autoResizeInput();
      input.focus();
    });
    grid.append(button);
  }

  wrapper.append(heading, grid);
  return wrapper;
}

function renderMessage(message, options = {}) {
  const article = document.createElement("article");
  article.className = `message ${message.role}${message.error ? " error" : ""}`;
  if (message.role === "user") {
    article.dataset.userContent = message.content;
  }

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = message.role === "user" ? "你" : "AI";

  const body = document.createElement("div");
  body.className = "message-body";
  if (message.reasoning) {
    const details = document.createElement("details");
    details.className = "provider-reasoning";
    const label = document.createElement("summary");
    label.textContent = "供应商提供的推理输出";
    const text = document.createElement("div");
    text.innerHTML = renderMarkdown(message.reasoning);
    details.append(label, text);
    body.append(details);
  }
  if (message.loading) {
    article.dataset.streaming = "true";
    const output = document.createElement("div");
    output.dataset.streamOutput = "true";
    output.innerHTML = renderMarkdown(message.content || "");
    const cursor = document.createElement("span");
    cursor.className = "stream-cursor";
    cursor.setAttribute("aria-label", "正在接收模型输出");
    body.append(output, cursor);
    if (!message.content && !message.reasoning)
      body.append(renderLoadingDots());
  } else {
    const output = document.createElement("div");
    output.innerHTML = renderMarkdown(message.content || "");
    body.append(output);
    if (message.incomplete) {
      const notice = document.createElement("p");
      notice.className = "stream-incomplete";
      notice.textContent =
        "输出不完整 · 已保留接收内容。重试将创建新的模型请求。";
      body.append(notice);
    }
    if (message.role === "assistant") {
      if (message.error) {
        body.append(renderRetryButton(message, options.onRetry));
      } else if (message.content) {
        if (message.model) {
          body.append(renderModelMeta(message));
        }
        body.append(renderActions(message.content));
      }
    }
  }

  const author = document.createElement("div");
  author.className = "message-author";
  author.textContent =
    message.role === "user" ? "Researcher" : "Research Copilot";
  body.prepend(author);
  if (message.role === "assistant")
    avatar.innerHTML = '<img src="/assets/logo.png" alt="">';
  article.append(avatar, body);
  return article;
}

function renderRetryButton(message, onRetry) {
  const wrapper = document.createElement("div");
  wrapper.className = "message-actions";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "retry-button";
  button.title = "重试";
  button.setAttribute("aria-label", "重试这条消息");
  button.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 12a9 9 0 1 0 3-6.7"></path>
      <path d="M3 4v5h5"></path>
    </svg>
    <span>重试</span>
  `;
  button.addEventListener("click", () => {
    if (typeof onRetry === "function") {
      onRetry();
    }
  });
  wrapper.append(button);
  return wrapper;
}

function renderLoadingDots() {
  const dots = document.createElement("div");
  dots.className = "loading-dots";
  dots.setAttribute("aria-label", "正在生成");
  dots.setAttribute("role", "status");
  dots.innerHTML = "<span></span><span></span><span></span>";
  return dots;
}

function renderModelMeta(message) {
  const meta = document.createElement("div");
  meta.className = "message-model-meta";
  meta.textContent = `使用模型：${message.model}`;
  return meta;
}

function renderActions(content) {
  const actions = document.createElement("div");
  actions.className = "message-actions";

  const copy = document.createElement("button");
  copy.className = "copy-button";
  copy.type = "button";
  copy.title = "复制";
  copy.setAttribute("aria-label", "复制回答");
  copy.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect width="14" height="14" x="8" y="8" rx="2"></rect>
      <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path>
    </svg>
  `;
  copy.addEventListener("click", async () => {
    try {
      await copyToClipboard(content);
      setButtonFeedback(copy, "已复制");
    } catch (_error) {
      setButtonFeedback(copy, "复制失败");
    }
  });

  const download = document.createElement("button");
  download.type = "button";
  download.className = "secondary-button";
  download.textContent = "导出 Markdown";
  download.setAttribute("aria-label", "将这条研究回答导出为 Markdown 文件");
  download.addEventListener("click", () => {
    const url = URL.createObjectURL(
      new Blob([content], { type: "text/markdown;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download =
      "research-note-" + new Date().toISOString().slice(0, 10) + ".md";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast("已导出 Markdown");
  });
  actions.append(copy, download);
  return actions;
}

async function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-9999px";
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) {
    throw new Error("Copy command failed.");
  }
}

function setButtonFeedback(button, label) {
  const previousTimer = feedbackTimers.get(button);
  if (previousTimer) {
    window.clearTimeout(previousTimer);
  }

  button.classList.toggle("copied", label === "已复制");
  button.title = label;
  button.setAttribute("aria-label", label);
  const timer = window.setTimeout(() => {
    button.classList.remove("copied");
    button.title = "复制";
    button.setAttribute("aria-label", "复制回答");
    feedbackTimers.delete(button);
  }, 1400);
  feedbackTimers.set(button, timer);
}

function autoResizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

async function sendMessage(message) {
  if (isSending) return;
  const session = getActiveSession();
  if (!session.messages.length) {
    session.title = titleFromMessage(message);
  }

  session.messages.push({ role: "user", content: message });
  session.messages.push({ role: "assistant", content: "", loading: true });
  pruneMessagesInMemory(session);
  session.updatedAt = Date.now();
  isSending = true;
  sendButton.disabled = true;
  saveState();
  render();

  try {
    const payload = await runInspectorTask(message, session);
    session.serverId = payload.session_id;
    const assistant = session.messages[session.messages.length - 1];
    assistant.loading = false;
    assistant.incomplete = Boolean(payload.incomplete);
    assistant.content =
      assistant.incomplete && assistant.content
        ? assistant.content + "\n\n---\n" + (payload.answer || "任务已中断")
        : payload.answer || "";
    assistant.model = payload.model || "";
    assistant.route = payload.route || "";
    assistant.error = Boolean(payload.runtime_error);
  } catch (error) {
    const assistant = session.messages[session.messages.length - 1];
    const errorMessage =
      error instanceof Error ? error.message : String(error || "未知错误");
    if (error?.payload?.session_id) {
      session.serverId = error.payload.session_id;
    }
    assistant.loading = false;
    assistant.error = true;
    // Status-aware hints: 429 → back off, 5xx → transient, default → generic.
    const hint =
      error instanceof ApiError && error.status === 429
        ? "请求过于频繁，请稍后再试。"
        : error instanceof ApiError && error.status >= 500
          ? "服务端异常，请稍后重试。"
          : `请求失败：${errorMessage}`;
    assistant.incomplete = Boolean(assistant.content || assistant.reasoning);
    assistant.content = assistant.content
      ? assistant.content + "\n\n---\n" + hint
      : hint;
  } finally {
    isSending = false;
    sendButton.disabled = false;
    pruneMessagesInMemory(session);
    session.updatedAt = Date.now();
    saveState();
    render();
    input.focus();
  }
}

async function loadKnowledgeBaseStatus() {
  try {
    const stats = await fetchJson("/api/kb/stats", {
      timeoutMs: QUICK_REQUEST_TIMEOUT_MS,
    });
    document.dispatchEvent(
      new CustomEvent("research:knowledge", { detail: stats }),
    );
  } catch (_error) {
    console.warn("无法读取知识库状态", _error);
  }
}

function setSidebarOpen(isOpen) {
  if (matchMedia("(min-width:721px)").matches) {
    document.body.classList.toggle("nav-collapsed", !isOpen);
  }
  document.body.classList.toggle("sidebar-open", isOpen);
  const visible = isOpen;
  menuButton.setAttribute("aria-expanded", String(visible));
  menuButton.title = visible ? "收起导航" : "展开导航";
  menuButton.setAttribute("aria-label", menuButton.title);
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || isSending) {
    return;
  }
  input.value = "";
  autoResizeInput();
  sendMessage(message);
});

input.addEventListener("input", autoResizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (typeof chatForm.requestSubmit === "function") {
      chatForm.requestSubmit();
    } else {
      chatForm.dispatchEvent(
        new Event("submit", { cancelable: true, bubbles: true }),
      );
    }
  }
});

newChatButton.addEventListener("click", startNewChat);
menuButton.addEventListener("click", () => {
  setSidebarOpen(!document.body.classList.contains("sidebar-open"));
});

document.addEventListener("click", (event) => {
  if (matchMedia("(min-width:721px)").matches) return;
  if (!document.body.classList.contains("sidebar-open")) {
    return;
  }
  const sidebar = document.querySelector(".sidebar");
  if (sidebar.contains(event.target) || menuButton.contains(event.target)) {
    return;
  }
  setSidebarOpen(false);
});

function isShortcut(event, key) {
  const meta = IS_MAC ? event.metaKey : event.ctrlKey;
  return (
    meta && !event.shiftKey && !event.altKey && event.key.toLowerCase() === key
  );
}

document.addEventListener("keydown", (event) => {
  // Cmd/Ctrl+/ → toggle sidebar (focus the input after opening).
  if (isShortcut(event, "/")) {
    event.preventDefault();
    const willOpen = !document.body.classList.contains("sidebar-open");
    setSidebarOpen(willOpen);
    if (willOpen) {
      // Focus the first session button for keyboard navigation.
      const firstSession = sessionList.querySelector(".session-item");
      firstSession?.focus();
    } else {
      input.focus();
    }
    return;
  }
  // Cmd/Ctrl+Shift+C → copy last assistant answer to clipboard.
  const metaKey = IS_MAC ? event.metaKey : event.ctrlKey;
  if (
    metaKey &&
    event.shiftKey &&
    !event.altKey &&
    event.key.toLowerCase() === "c"
  ) {
    event.preventDefault();
    const session = getActiveSession();
    for (let index = session.messages.length - 1; index >= 0; index -= 1) {
      const msg = session.messages[index];
      if (msg.role === "assistant" && msg.content && !msg.error) {
        copyToClipboard(msg.content)
          .then(() => showToast("已复制最后一条回答"))
          .catch(() => showToast("复制失败"));
        return;
      }
    }
    showToast("没有可复制的回答");
    return;
  }
  if (event.key === "Escape") {
    if (
      document.body.classList.contains("sidebar-open") &&
      (matchMedia("(max-width:720px)").matches ||
        document.body.classList.contains("landing-mode"))
    ) {
      setSidebarOpen(false);
      menuButton.focus();
      return;
    }
    // Esc while focus is in the textarea clears it (preserves focus).
    if (document.activeElement === input && input.value) {
      event.preventDefault();
      input.value = "";
      autoResizeInput();
    }
  }
});

function showToast(text) {
  let toast = document.querySelector("#toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    toast.className = "toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    document.body.append(toast);
  }
  toast.textContent = text;
  toast.classList.add("toast-visible");
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(
    () => toast.classList.remove("toast-visible"),
    Math.min(8000, Math.max(3000, text.length * 80)),
  );
}

render();
loadKnowledgeBaseStatus();

// Inspector reads only server runtime events; no demonstration or synthetic data.
const liveRuntime = new LiveRuntime((sessionId, status) => {
  if (getActiveSession()?.serverId === sessionId) {
    inspectorSessionId = sessionId;
    showInspector(status);
  }
});
addEventListener("pagehide", () => liveRuntime.close(), { once: true });
let inspectorSessionId = null;
let inspectorCursor = 0;
let inspectorStatus = null;
let inspectorPolling = false;
const terminalStates = new Set([
  "completed",
  "failed",
  "exhausted",
  "cancelled",
]);

function inspectorBudget() {
  const budget = {};
  const form = document.getElementById("budgetForm");
  if (!form.checkValidity()) {
    location.hash = "settings";
    document.dispatchEvent(new CustomEvent("research:edit-budget"));
    requestAnimationFrame(() => form.reportValidity());
    throw new Error("请检查预算输入");
  }
  for (const [key, value] of new FormData(form)) {
    budget[key] = value === "" ? null : Number(value);
  }
  if (
    budget.max_cost != null &&
    (!(budget.input_price_per_million > 0) ||
      !(budget.output_price_per_million > 0))
  ) {
    location.hash = "settings";
    document.dispatchEvent(new CustomEvent("research:edit-budget"));
    throw new Error("费用上限需要正数输入与输出单价");
  }
  return budget;
}

let streamRenderPending = false;
function updateStreamingMessage(status) {
  const session = getActiveSession();
  const message = session?.messages.at(-1);
  if (!message?.loading || !status.partial_output) return;
  if (!applyStreamSnapshot(message, status.partial_output)) return;
  if (!streamRenderPending) {
    streamRenderPending = true;
    requestAnimationFrame(() => {
      streamRenderPending = false;
      if (getActiveSession() !== session) return;
      const article =
        messagesEl.querySelector(".message-list")?.lastElementChild;
      const shouldStick =
        messagesEl.scrollHeight -
          messagesEl.scrollTop -
          messagesEl.clientHeight <
        AUTO_SCROLL_THRESHOLD;
      if (
        !article?.matches('[data-streaming="true"]') ||
        !updateStreamArticle(article, message)
      )
        return;
      if (shouldStick) messagesEl.scrollTop = messagesEl.scrollHeight;
    });
  }
}
function showInspector(status) {
  if (
    status.run_id &&
    inspectorStatus?.run_id === status.run_id &&
    status.cursor < inspectorStatus.cursor
  )
    return;
  updateStreamingMessage(status);
  document.dispatchEvent(
    new CustomEvent("research:runtime", {
      detail: { status, session: getActiveSession() },
    }),
  );
  inspectorStatus = status;
  const stateLabels = {
    idle: "就绪",
    reasoning: "正在生成回答",
    thinking: "正在生成回答",
    retrieving: "正在检索论文",
    tool_running: "正在执行工具",
    paused: "已暂停",
    waiting_approval: "等待工具执行确认",
    completed: "已完成",
    failed: "执行失败",
    cancelled: "已停止",
    exhausted: "已达到预算上限",
  };
  const bar = document.getElementById("taskStatusBar");
  bar.hidden = !status.run_id && status.state === "idle";
  document.getElementById("taskStatusText").textContent =
    (stateLabels[status.state] ||
      (status.running ? "正在执行研究" : status.state)) +
    (status.worker_error || status.error
      ? " · " + (status.worker_error || status.error)
      : "");
  const current = getActiveSession();
  const answer = current.messages[current.messages.length - 1];
  if (answer?.role === "assistant" && current.serverId === inspectorSessionId) {
    const previous =
      answer.execution?.run_id === status.run_id ? answer.execution : null;
    const events = new Map(
      (previous?.events || []).map((event) => [event.event_id, event]),
    );
    for (const event of status.events || []) {
      if (executionEventNames.has(event.name)) events.set(event.event_id, event);
    }
    answer.execution = {
      run_id: status.run_id,
      state: status.state,
      model: status.model,
      budget: status.budget,
      error: status.worker_error || status.error,
      events: [...events.values()].slice(-160),
    };
  }
  document.getElementById("runtimeState").textContent =
    status.state + (status.running ? " · 执行中" : "");
  const budget = status.budget;
  document.getElementById("runtimeBudget").textContent = budget
    ? `步骤 ${budget.used.steps}/${budget.limits.max_steps} · LLM ${budget.used.llm_calls}/${budget.limits.max_llm_calls} · 工具 ${budget.used.tool_calls}/${budget.limits.max_tool_calls}\n` +
      `Token ${budget.used.tokens}/${budget.limits.max_tokens ?? "∞"} · 费用 ${budget.limits.input_price_per_million > 0 && budget.limits.output_price_per_million > 0 ? Number(budget.used.cost).toFixed(6) : "未配置单价"}/${budget.limits.max_cost ?? "∞"} · ${Number(budget.used.seconds).toFixed(1)} 秒\n` +
      `用量${budget.used.estimated_usage ? "含未结算预留值" : "已结算"} · 重试 ${budget.used.retries} · 恢复 ${budget.used.recoveries}`
    : "暂无预算消耗";
  document.getElementById("runtimeError").textContent =
    status.worker_error || status.error || "";
  document.getElementById("runtimePending").textContent = status.pending_tool
    ? JSON.stringify(status.pending_tool, null, 2)
    : "";
  document.getElementById("interruptedTool").hidden = !(
    status.state === "waiting_approval" && status.phase === "tool_inflight"
  );
  if (status.run_id) {
    document.getElementById("restoreRunId").value = status.run_id;
    const session = getActiveSession();
    if (
      session?.serverId === inspectorSessionId &&
      session.runId !== status.run_id
    ) {
      session.runId = status.run_id;
      saveState();
    }
  }
  for (const button of document.querySelectorAll("[data-task-action]")) {
    const action = button.dataset.taskAction;
    if (button.closest("#taskStatusBar")) {
      button.hidden =
        action === "resume"
          ? status.state !== "paused"
          : action === "approve"
            ? status.state !== "waiting_approval"
            : !status.running;
    }
    button.disabled =
      action === "resume"
        ? status.state !== "paused" || status.running
        : action === "approve"
          ? status.state !== "waiting_approval" ||
            status.phase === "tool_inflight" ||
            status.running
          : action === "resolve"
            ? status.phase !== "tool_inflight" || status.running
            : action === "pause"
              ? !status.running
              : status.state === "idle" || terminalStates.has(status.state);
  }
  if (status.gap)
    document.getElementById("runtimeError").textContent +=
      " 部分旧事件已从有界缓冲区移除。";
  inspectorCursor = status.cursor;
}

async function pollInspector() {
  if (inspectorPolling || !inspectorSessionId) return;
  inspectorPolling = true;
  const sessionId = inspectorSessionId;
  if (liveRuntime.follow(sessionId) && liveRuntime.cached(sessionId)) {
    inspectorPolling = false;
    return liveRuntime.cached(sessionId);
  }
  try {
    const status = await fetchJson(
      `/api/tasks/status?session_id=${encodeURIComponent(sessionId)}&after=${inspectorCursor}`,
      { timeoutMs: QUICK_REQUEST_TIMEOUT_MS },
    );
    if (sessionId === inspectorSessionId) showInspector(status);
    return status;
  } finally {
    inspectorPolling = false;
  }
}

async function runInspectorTask(message, session) {
  const payload = await fetchJson("/api/tasks/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: session.serverId,
      budget: inspectorBudget(),
      retrieval_mode: document.getElementById("composerRetrieval").value,
      approval_tools: document.getElementById("confirmSearch").checked
        ? ["search_knowledge"]
        : [],
    }),
  });
  session.serverId = payload.session_id;
  liveRuntime.stop(payload.session_id);
  liveRuntime.follow(payload.session_id);
  inspectorSessionId = payload.session_id;
  inspectorCursor = 0;
  document.getElementById("runtimeEvents").replaceChildren();

  while (true) {
    const status =
      liveRuntime.cached(payload.session_id) ||
      (await fetchJson(
        `/api/tasks/status?session_id=${encodeURIComponent(payload.session_id)}&after=${inspectorSessionId === payload.session_id ? inspectorCursor : 0}`,
        { timeoutMs: QUICK_REQUEST_TIMEOUT_MS },
      ));
    if (getActiveSession()?.serverId === payload.session_id)
      showInspector(status);
    if (status && !status.running && status.state !== "idle") {
      if (status.worker_error) throw new Error(status.worker_error);
      return {
        session_id: payload.session_id,
        answer: status.result || `任务已暂停：${status.state}`,
        model: status.model,
        route: status.route,
        runtime_error: ["failed", "exhausted"].includes(status.state),
        incomplete:
          ["failed", "exhausted", "cancelled"].includes(status.state) &&
          Boolean(status.partial_output?.content || status.partial_output?.reasoning),
      };
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

async function taskAction(action, extras = {}) {
  const session = getActiveSession();
  if (action === "restore" && session.serverId) {
    try {
      await fetchJson(
        `/api/tasks/status?session_id=${encodeURIComponent(session.serverId)}`,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 400)
        session.serverId = null;
      else throw error;
    }
  }
  if (!session.serverId) {
    const created = await fetchJson("/api/session", { method: "POST" });
    session.serverId = created.session_id;
    saveState();
  }
  inspectorSessionId = session.serverId;
  await fetchJson(`/api/tasks/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: session.serverId, ...extras }),
  });
  await pollInspector();
}

for (const button of document.querySelectorAll("[data-task-action]")) {
  button.addEventListener("click", async () => {
    try {
      await taskAction(button.dataset.taskAction, {
        call_id: inspectorStatus?.pending_tool?.id,
        approved: button.dataset.approved === "true",
        result: document.getElementById("verifiedToolResult").value,
      });
    } catch (error) {
      document.getElementById("runtimeError").textContent = error.message;
    }
  });
}
document.getElementById("restoreTask").addEventListener("click", async () => {
  try {
    inspectorCursor = 0;
    await taskAction("restore", {
      run_id: document.getElementById("restoreRunId").value.trim(),
    });
  } catch (error) {
    document.getElementById("runtimeError").textContent = error.message;
  }
});
setInterval(async () => {
  const session = getActiveSession();
  if (!session?.serverId) {
    if (inspectorSessionId) {
      inspectorSessionId = null;
      inspectorCursor = 0;
      document.getElementById("runtimeEvents").replaceChildren();
      showInspector({ state: "idle", running: false, cursor: 0, events: [] });
    }
    return;
  }
  if (inspectorSessionId !== session.serverId) {
    inspectorSessionId = session.serverId;
    inspectorCursor = 0;
    document.getElementById("restoreRunId").value = session.runId || "";
    document.getElementById("runtimeEvents").replaceChildren();
  }
  try {
    const status = await pollInspector();
    if (
      status &&
      !isSending &&
      terminalStates.has(status.state) &&
      status.result
    ) {
      const last = session.messages.at(-1);
      if (
        last?.role === "assistant" &&
        !last.loading &&
        last.content !== status.result
      ) {
        last.content = status.result;
        last.error = status.state !== "completed";
        saveState();
        renderMessages();
      }
    }
  } catch (error) {
    document.getElementById("runtimeError").textContent = error.message;
  }
}, 600);

// Real local ingestion; sequential uploads keep memory and KB writes bounded.
const importDialog = document.getElementById("pdfImportDialog");
document.getElementById("openPdfImport").onclick = () =>
  importDialog.showModal();
for (const id of ["closePdfImport", "cancelPdfImport"]) {
  document.getElementById(id).onclick = () => importDialog.close();
}
const pdfUpload = document.getElementById("pdfUpload");
const uploadLabel = document.getElementById("pdfUploadLabel");
pdfUpload?.addEventListener("change", async () => {
  const files = [...pdfUpload.files];
  importDialog.close();
  pdfUpload.disabled = true;
  uploadLabel.setAttribute("aria-disabled", "true");
  uploadLabel.setAttribute("aria-busy", "true");
  uploadLabel.querySelector(".upload-button-text").textContent = "正在导入…";
  const list = document.getElementById("importResults");
  try {
    for (const file of files) {
      const row = document.createElement("li");
      list.prepend(row);
      while (list.children.length > 30) list.lastChild.remove();
      row.textContent = `${file.name} · 正在上传并提取文字…`;
      try {
        if (file.size > 20 * 1024 * 1024)
          throw new Error("文件超过 20 MiB，请拆分后上传。");
        const result = await fetchJson(
          "/api/kb/import?filename=" + encodeURIComponent(file.name),
          {
            method: "POST",
            headers: { "Content-Type": "application/pdf" },
            body: file,
            timeoutMs: 180000,
          },
        );
        row.remove();
        await loadKnowledgeBaseStatus();
      } catch (error) {
        row.className = "import-error";
        row.textContent = `${file.name} · ${error.message}${error.message.includes("超时") ? " 请检查文档列表后重试。" : ""}`;
      }
    }
  } finally {
    pdfUpload.value = "";
    pdfUpload.disabled = false;
    uploadLabel.removeAttribute("aria-disabled");
    uploadLabel.removeAttribute("aria-busy");
    uploadLabel.querySelector(".upload-button-text").textContent =
      "选择论文 PDF";
  }
});

mountWorkspace({
  getSession: getActiveSession,
  getSessions: () => state.sessions,
  newSession: startNewChat,
  selectSession: setActiveSession,
  prompt: (text) => {
    input.value = text;
    autoResizeInput();
    input.focus();
  },
  send: (text) => sendMessage(text),
  reloadKnowledge: loadKnowledgeBaseStatus,
  openBranch: (data) => {
    startNewChat();
    const session = getActiveSession();
    session.serverId = data.session_id;
    session.runId = data.run_id;
    session.title = `Debug branch · ${data.run_id.slice(0, 8)}`;
    session.messages = (data.messages || [])
      .filter((m) => ["user", "assistant"].includes(m.role) && m.content)
      .map((m) => ({ role: m.role, content: m.content }));
    saveState();
    render();
    location.hash = "workspace";
    inspectorSessionId = data.session_id;
    inspectorCursor = 0;
    liveRuntime.follow(data.session_id);
  },
  toast: showToast,
  copy: copyToClipboard,
});
