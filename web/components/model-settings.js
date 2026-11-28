import { icon } from "./icons.js?v=model-icon-2";
import { fetchJson } from "../lib/api.js";
import { escapeHtml as esc } from "../lib/markdown.js";
const roles = {
  default: "默认模型",
  simple: "快速模型",
  complex: "深度模型",
  embedding: "向量模型",
};
export function mountModelSettings() {
  const host = document.getElementById("modelSettings");
  const budgetPanel = document.getElementById("modelBudgetPanel");
  let openBudget = () => {};
  document.addEventListener("research:edit-budget", () => openBudget());
  let current = null,
    saving = false,
    activeRole = "simple";
  const headers = {
    "Content-Type": "application/json",
    "X-Requested-With": "research-copilot",
  };
  let revealEpoch = 0;
  const maskKeys = (clearAll = false) => {
    revealEpoch++;
    host.querySelectorAll("[name=api_key]").forEach((input) => {
      input.type = "password";
      const field = input.closest("fieldset");
      if (clearAll || field.querySelector("[name=key_action]").value !== "set")
        input.value = "";
      delete input.dataset.savedMask;
      if (!clearAll && field.querySelector("[name=key_action]").value === "keep") {
        const preview = current?.profiles[field.dataset.profile]?.key_preview || "";
        if (preview) {
          input.value = preview;
          input.type = "text";
          input.dataset.savedMask = "true";
        }
      }
      const button = field.querySelector("[data-toggle-key]");
      if (button) {
        button.innerHTML = icon("eye");
        button.setAttribute("aria-label", "显示 API 密钥");
        button.setAttribute("aria-pressed", "false");
      }
    });
  };
  const passwordClear = () => maskKeys(true);
  const caretToEnd = (input) => {
    const end = input.value.length;
    input.setSelectionRange(end, end);
    input.scrollLeft = input.scrollWidth;
  };
  function render(data) {
    if (
      !data?.profiles ||
      Object.keys(roles).some((role) => !data.profiles[role])
    )
      throw new Error("模型配置格式无效，请刷新页面");
    const editable = data.can_edit;
    current = data;
    const glyphs = {
      default: "model",
      simple: "activity",
      complex: "layers",
      embedding: "library",
    };
    // Retain the original form, values and handlers across model save/reset renders.
    passwordClear();
    budgetPanel?.remove();
    function connectionCard(role) {
      const label = roles[role];
      const p = data.profiles[role];
      return `<article class="connection-card" data-connection="${role}">
      <span class="connection-icon">${icon(glyphs[role])}</span>
      <div class="connection-copy"><div class="connection-title"><strong data-model-caption="${role}">${esc(p.model_name)}</strong><span class="connection-role">${label}</span></div><span class="connection-url" data-model-url="${role}">${esc(p.base_url)}</span></div>
      <div class="connection-meta"><span class="connection-usage" data-model-usage="${role}"></span><code data-key-preview="${role}">${esc(p.key_preview || (p.key_configured ? "********" : "未设置密钥"))}</code></div>
      <button type="button" class="connection-edit" id="profile-tab-${role}" data-model-tab="${role}" aria-controls="profile-panel-${role}" aria-label="编辑${label}">编辑 ${icon("settings")}</button>
    </article>`;
    }
    host.innerHTML = `<div class="model-console"><form id="modelSettingsForm">
      <div id="modelConnectionList">
      <section aria-labelledby="retrievalSettingsTitle"><header class="connection-toolbar"><h2 id="retrievalSettingsTitle">知识检索</h2></header>
      <div class="connection-list">${connectionCard("embedding")}</div></section>
      <section aria-labelledby="chatSettingsTitle">
      <header class="connection-toolbar"><h2 id="chatSettingsTitle">对话模型</h2><label class="connection-routing"><span>自动路由</span><span class="model-toggle"><input id="modelRouterEnabled" role="switch" type="checkbox" aria-label="自动选择快速或深度模型" ${data.router_enabled ? "checked" : ""} ${!editable ? "disabled" : ""}><span aria-hidden="true"></span></span></label></header>
      <div class="connection-routing-summary"><span id="modelRoutingPath"></span>
      <button type="button" id="editDefaultKey" class="secondary-button" data-model-tab="default" hidden>管理默认密钥</button>
      </div>
      <div class="connection-list">${["default", "simple", "complex"].map(connectionCard).join("")}</div>
      </section>
      </div>
      <div id="modelConnectionEditor" class="connection-editor" hidden>
        <header class="connection-editor-header"><button type="button" id="backToModels" aria-label="返回模型列表"><span aria-hidden="true">←</span></button><h2 id="modelEditorTitle">编辑模型</h2></header>
        <div class="model-profile-grid">${Object.entries(roles)
          .map(([role, label]) => {
            const p = data.profiles[role];
            return `<section id="profile-panel-${role}" aria-label="${label}配置" hidden>
          <header class="model-profile-heading"><span class="model-role-icon">${icon(glyphs[role])}</span><h3>连接配置</h3><span class="model-key-status ${p.key_configured ? "has-key" : ""}">${p.key_configured ? (p.key_mode === "inherit" ? "使用默认密钥" : "密钥已保存") : "未设置密钥"}</span></header>
          <fieldset data-profile="${role}" ${!editable ? "disabled" : ""}>
            <label><span class="model-field-label">模型名称</span><div class="model-input-frame">${icon("model")}<input name="model_name" aria-label="${label}名称" required maxlength="200" value="${esc(p.model_name)}" autocomplete="off" spellcheck="false"></div></label>
            <label><span class="model-field-label">接口地址</span><div class="model-input-frame">${icon("orbit")}<input name="base_url" aria-label="${label} API Base URL" type="text" inputmode="url" required value="${esc(p.base_url)}" autocomplete="off" spellcheck="false"></div></label>
            <label><span class="model-field-label">API 密钥</span><div class="model-input-frame"><input name="api_key" type="password" aria-label="${label} API Key" autocomplete="new-password" spellcheck="false" placeholder="${esc(p.key_preview || (p.key_configured ? "********" : "粘贴 API 密钥"))}"><button class="model-key-toggle" type="button" data-toggle-key aria-label="显示 API 密钥" aria-pressed="false">${icon("eye")}</button></div></label>
            <select name="key_action" hidden aria-hidden="true" tabindex="-1"><option value="keep">保留</option><option value="set">替换</option><option value="inherit">使用默认密钥</option><option value="clear">移除</option></select>
            <div class="model-key-actions"><span data-key-hint>留空保留已保存的密钥</span><div>${["simple", "complex"].includes(role) ? '<button type="button" data-key-action="inherit">使用默认密钥</button>' : ""}<button type="button" data-key-action="clear">移除</button></div></div>
          </fieldset>
          <div class="model-effective-scope">${icon(role === "embedding" ? "refresh" : "play")}<span>${role === "embedding" ? "重启服务后生效" : role === "default" ? "自动路由关闭时使用" : "下次新任务生效"}</span></div>
        </section>`;
          })
          .join("")}</div></div>
      <footer class="model-console-footer"><span id="modelDraftStatus" class="model-draft-status" role="status"></span><div class="model-setting-actions" id="modelSettingActions" hidden><button id="saveModels" class="primary-button" type="submit" disabled>${icon("check")}保存配置</button></div></footer>
      </form></div>`;
    if (budgetPanel) {
      budgetPanel.hidden = true;
      host.querySelector(".model-console").append(budgetPanel);
    }
    const list = document.getElementById("modelConnectionList");
    const editor = document.getElementById("modelConnectionEditor");
    const activate = (role, focus = true) => {
      maskKeys();
      activeRole = role;
      host.querySelector(".model-console").classList.add("is-editing");
      if (budgetPanel) budgetPanel.hidden = false;
      list.hidden = true;
      editor.hidden = false;
      document.getElementById("modelSettingActions").hidden = false;
      document.getElementById("modelEditorTitle").textContent =
        "编辑" + roles[role];
      for (const key of Object.keys(roles))
        document.getElementById("profile-panel-" + key).hidden = key !== role;
      if (focus)
        editor
          .querySelector('[data-profile="' + role + '"] [name=model_name]')
          .focus();
    };
    const back = () => {
      if (saving) return;
      maskKeys();
      host.querySelector(".model-console").classList.remove("is-editing");
      if (budgetPanel) budgetPanel.hidden = true;
      editor.hidden = true;
      list.hidden = false;
      document.getElementById("modelSettingActions").hidden =
        document.getElementById("saveModels").disabled;
      host.querySelectorAll("[data-profile]").forEach((field) => {
        const role = field.dataset.profile;
        host.querySelector('[data-model-url="' + role + '"]').textContent =
          field.querySelector("[name=base_url]").value;
        const action = field.querySelector("[name=key_action]").value;
        host.querySelector('[data-key-preview="' + role + '"]').textContent =
          action === "set"
            ? "待保存新密钥"
            : action === "clear"
              ? "待移除密钥"
              : action === "inherit"
                ? "待使用默认密钥"
                : data.profiles[role].key_preview ||
                  (data.profiles[role].key_configured
                    ? "********"
                    : "未设置密钥");
      });
      const trigger = activeRole === "default" && !document.getElementById("editDefaultKey").hidden
        ? "editDefaultKey"
        : "profile-tab-" + activeRole;
      document.getElementById(trigger).focus();
    };
    openBudget = () => {
      const automatic = document.getElementById("modelRouterEnabled").checked;
      activate(automatic ? activeRole : "default", false);
      budgetPanel?.scrollIntoView({ block: "nearest" });
    };
    document.getElementById("backToModels").onclick = back;
    editor.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        back();
      }
    });
    host.querySelectorAll("[data-model-tab]").forEach((button) => {
      button.onclick = () => activate(button.dataset.modelTab);
    });
    const updateRouting = () => {
      const automatic = document.getElementById("modelRouterEnabled").checked;
      document.getElementById("modelRoutingPath").innerHTML = automatic
        ? "按任务复杂度选择快速或深度模型"
        : "使用默认模型处理任务";
      document.getElementById("editDefaultKey").hidden = !automatic;
      for (const role of Object.keys(roles)) {
        const used =
          role === "default"
            ? !automatic
            : ["simple", "complex"].includes(role) && automatic;
        const badge = host.querySelector('[data-model-usage="' + role + '"]');
        badge.textContent = used ? (automatic ? "自动路由" : "默认使用") : "";
        badge.hidden = !used;
        const card = host.querySelector('[data-connection="' + role + '"]');
        card.hidden = role !== "embedding" && !used;
        card.classList.toggle("is-active", used);
      }
    };
    updateRouting();
    document
      .getElementById("modelRouterEnabled")
      .addEventListener("change", updateRouting);
    const form = document.getElementById("modelSettingsForm");
    const dirty = () => {
      document.getElementById("modelSettingActions").hidden = false;
      document.getElementById("modelDraftStatus").textContent =
        "有未保存的更改";
      document.getElementById("saveModels").disabled = !editable || saving;
      status("");
    };
    form.addEventListener("input", () => {
      dirty();
      host.querySelectorAll("[data-profile]").forEach((field) => {
        host.querySelector(
          '[data-model-caption="' + field.dataset.profile + '"]',
        ).textContent =
          field.querySelector("[name=model_name]").value || "未填写模型";
      });
    });
    form.addEventListener("change", dirty);
    form.addEventListener(
      "invalid",
      (event) => {
        const field = event.target.closest("[data-profile]");
        if (field) activate(field.dataset.profile, false);
      },
      true,
    );
    host.querySelectorAll(".model-input-frame input").forEach((input) => {
      if (input.name === "base_url") {
        const validateUrl = () => {
          let valid = true;
          try {
            const url = new URL(input.value);
            valid = ["https:", "http:"].includes(url.protocol);
          } catch {
            valid = false;
          }
          input.setCustomValidity(
            input.value && !valid ? "请输入完整的 HTTP(S) 接口地址" : "",
          );
        };
        input.addEventListener("input", validateUrl);
        validateUrl();
      }
    });
    host.querySelectorAll("[data-profile]").forEach((field) => {
      const input = field.querySelector("[name=api_key]");
      const action = field.querySelector("[name=key_action]");
      const hint = field.querySelector("[data-key-hint]");
      const updateKey = (value) => {
        action.value = value;
        hint.textContent = {
          keep: "留空保留已保存的密钥",
          set: "保存后替换密钥",
          inherit: "保存后使用默认模型的密钥",
          clear: "保存后移除密钥",
        }[value];
        input.placeholder =
          value === "clear"
            ? "未设置密钥"
            : value === "inherit"
              ? "使用默认密钥"
              : data.profiles[field.dataset.profile].key_preview ||
                (data.profiles[field.dataset.profile].key_configured
                  ? "********"
                  : "粘贴 API 密钥");
        dirty();
      };
      input.oninput = () => {
        revealEpoch++;
        delete input.dataset.savedMask;
        updateKey(input.value ? "set" : "keep");
      };
      // Saved stars are display characters, never a replacement credential.
      // Typing/pasting replaces the saved key; the eye enables editing its value.
      input.addEventListener("beforeinput", () => {
        if (!input.dataset.savedMask) return;
        delete input.dataset.savedMask;
        input.value = "";
        input.type = "password";
      });
      const eye = field.querySelector("[data-toggle-key]");
      eye.onclick = async () => {
        if (input.type === "text" && !input.dataset.savedMask) {
          maskKeys();
          input.focus();
          return;
        }
        const epoch = ++revealEpoch;
        eye.disabled = true;
        eye.setAttribute("aria-busy", "true");
        try {
          let value = input.value;
          if (action.value !== "set") {
            let source = field;
            if (
              action.value === "inherit" ||
              (action.value === "keep" &&
                data.profiles[field.dataset.profile].key_mode === "inherit")
            )
              source = host.querySelector('[data-profile="default"]');
            const sourceAction =
              source.querySelector("[name=key_action]").value;
            if (sourceAction === "set")
              value = source.querySelector("[name=api_key]").value;
            else if (
              sourceAction === "clear" ||
              !data.profiles[source.dataset.profile].key_configured
            )
              value = "";
            else {
              const grant = await fetchJson("/api/settings/models/unlock", {
                method: "POST",
                headers,
                body: "{}",
              });
              if (epoch !== revealEpoch || saving || !input.isConnected) return;
              const result = await fetchJson("/api/settings/models/reveal", {
                method: "POST",
                headers: { ...headers, "X-Config-Token": grant.edit_token },
                body: JSON.stringify({
                  role: source.dataset.profile,
                  revision: current.revision,
                }),
              });
              value = result.api_key;
            }
          }
          if (epoch !== revealEpoch || saving || !input.isConnected) return;
          if (typeof value !== "string") throw new Error("无效密钥响应");
          delete input.dataset.savedMask;
          input.value = value;
          input.type = "text";
          eye.innerHTML = icon("eyeOff");
          eye.setAttribute("aria-label", "隐藏 API 密钥");
          eye.setAttribute("aria-pressed", "true");
          input.focus();
          caretToEnd(input);
        } catch {
          if (epoch === revealEpoch && input.isConnected)
            status("密钥暂时无法显示，请重试", true);
        } finally {
          if (eye.isConnected) {
            eye.disabled = saving || !editable;
            eye.removeAttribute("aria-busy");
          }
        }
      };
      field.querySelectorAll("[data-key-action]").forEach((button) => {
        button.onclick = () => {
          maskKeys();
          input.value = "";
          updateKey(button.dataset.keyAction);
        };
      });
    });
    maskKeys();
    document.getElementById("modelSettingsForm").onsubmit = async (event) => {
      event.preventDefault();
      if (saving || !editable) return;
      maskKeys();
      saving = true;
      const button = document.getElementById("saveModels");
      button.disabled = true;
      button.textContent = "保存中…";
      form.setAttribute("aria-busy", "true");
      const profiles = {};
      for (const field of host.querySelectorAll("[data-profile]")) {
        const profile = {
          model_name: field.querySelector("[name=model_name]").value.trim(),
          base_url: field.querySelector("[name=base_url]").value.trim(),
          key_action: field.querySelector("[name=key_action]").value,
        };
        if (profile.key_action === "set")
          profile.api_key = field.querySelector("[name=api_key]").value;
        profiles[field.dataset.profile] = profile;
      }
      if (
        Object.values(profiles).some(
          (p) => p.key_action === "set" && !p.api_key,
        )
      ) {
        saving = false;
        button.disabled = false;
        button.textContent = "保存配置";
        form.removeAttribute("aria-busy");
        status("请重新输入要替换的密钥", true);
        return;
      }
      const payload = {
        profiles,
        router_enabled: document.getElementById("modelRouterEnabled").checked,
        revision: current.revision,
      };
      form
        .querySelectorAll("input, select, button, fieldset")
        .forEach((node) => {
          node.disabled = true;
        });
      try {
        // Obtain the same-origin write nonce at save time; no user approval step.
        const grant = await fetchJson("/api/settings/models/unlock", {
          method: "POST",
          headers,
          body: "{}",
        });
        const result = await fetchJson("/api/settings/models", {
          method: "POST",
          headers: { ...headers, "X-Config-Token": grant.edit_token },
          body: JSON.stringify(payload),
        });
        passwordClear();
        render(result);
        status("已保存到本机");
        document.dispatchEvent(new CustomEvent("research:models-saved"));
      } catch (error) {
        passwordClear();
        status(error.message, true);
        if (form.isConnected) {
          form
            .querySelectorAll("input, select, button, fieldset")
            .forEach((node) => {
              node.disabled = false;
            });
          button.textContent = "重新保存";
        }
      } finally {
        saving = false;
        form.removeAttribute("aria-busy");
      }
    };
  }
  function status(text, error = false) {
    const node = document.getElementById("modelSettingsStatus");
    node.textContent = text;
    node.classList.toggle("settings-error", error);
  }
  fetchJson("/api/settings/models")
    .then((data) => render(data))
    .catch((error) => {
      host.textContent = "模型配置暂不可用";
      status(error.message, true);
    });
  const lock = () => {
    passwordClear();
    if (current) render(current);
  };
  addEventListener("hashchange", () => {
    if (location.hash !== "#settings") lock();
  });
  addEventListener("pagehide", lock, { once: true });
}
