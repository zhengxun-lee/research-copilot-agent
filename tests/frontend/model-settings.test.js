import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { mountModelSettings } from "../../web/components/model-settings.js";

test("model editor edits directly, acquires nonce only on save, and never persists secrets in browser", async () => {
  const dom = new JSDOM(
    '<div id="modelSettings"></div><p id="modelSettingsStatus"></p><section id="modelBudgetPanel" hidden><form id="budgetForm"><input name="max_steps" value="10" type="number" min="1"></form><button id="saveBudget" type="button">保存预算</button></section>',
    { url: "http://localhost/#settings" },
  );
  const w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  for (const key of [
    "window",
    "document",
    "localStorage",
    "CustomEvent",
    "location",
  ])
    globalThis[key] = key === "window" ? w : w[key];
  globalThis.addEventListener = w.addEventListener.bind(w);
  let view = {
    revision: 0,
    can_edit: true,
    router_enabled: true,
    profiles: Object.fromEntries(
      ["default", "simple", "complex", "embedding"].map((role) => [
        role,
        {
          model_name: role,
          base_url: "https://api.example.test/v1",
          key_configured: true,
          key_mode: "set",
          key_preview: "*****************",
        },
      ]),
    ),
  };
  const calls = [];
  let failSave = false;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    let body = view;
    if (url.endsWith("/unlock"))
      body = { edit_token: "unit-edit-token", expires_in: 600 };
    else if (options.method === "POST") {
      if (failSave)
        return new Response(JSON.stringify({ error: "保存失败" }), {
          status: 500,
        });
      view = {
        ...view,
        revision: 1,
        router_enabled: JSON.parse(options.body).router_enabled,
      };
      body = view;
    }
    return new Response(JSON.stringify(body), { status: 200 });
  };
  const originalBudgetForm = document.getElementById("budgetForm");
  let budgetSaved = 0;
  document.getElementById("saveBudget").onclick = () => budgetSaved++;
  mountModelSettings();
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(document.getElementById("saveModels").disabled, true);
  assert.equal(document.getElementById("unlockModels"), null);
  assert.equal(document.getElementById("modelRouterEnabled").disabled, false);
  assert.equal(document.querySelector("[data-profile=simple]").disabled, false);
  assert.equal(
    document.querySelector("[name=api_key]").placeholder,
    "*****************",
  );
  assert.equal(calls.length, 1);
  assert.equal(document.getElementById("modelBudgetPanel").hidden, true);
  assert.equal(originalBudgetForm.parentElement.closest("form"), null);
  const visibleRoles = () =>
    [...document.querySelectorAll(".connection-card:not([hidden])")].map(
      (card) => card.dataset.connection,
    );
  assert.deepEqual(visibleRoles(), [
    "embedding",
    "simple",
    "complex",
  ]);
  assert.equal(document.querySelector('[data-connection="embedding"]').closest("section").getAttribute("aria-labelledby"), "retrievalSettingsTitle");
  const defaultKey = document.getElementById("editDefaultKey");
  assert.equal(defaultKey.hidden, false);
  defaultKey.click();
  assert.equal(document.getElementById("profile-panel-default").hidden, false);
  document.getElementById("backToModels").click();
  assert.equal(document.activeElement, defaultKey);
  document.getElementById("modelRouterEnabled").click();
  assert.deepEqual(visibleRoles(), ["embedding", "default"]);
  assert.equal(document.getElementById("saveModels").disabled, false);
  assert.equal(document.getElementById("modelRouterEnabled").checked, false);
  assert.equal(
    calls.filter(
      (c) => c.options.method === "POST" && c.url === "/api/settings/models",
    ).length,
    0,
  );
  assert.match(
    document.getElementById("modelDraftStatus").textContent,
    /未保存/,
  );
  assert.equal(document.getElementById("modelConnectionEditor").hidden, true);
  assert.equal(document.querySelectorAll(".connection-card").length, 4);
  document.getElementById("modelRouterEnabled").click();
  assert.deepEqual(visibleRoles(), [
    "embedding",
    "simple",
    "complex",
  ]);
  document.getElementById("profile-tab-simple").click();
  assert.equal(document.getElementById("modelConnectionList").hidden, true);
  assert.equal(document.getElementById("modelConnectionEditor").hidden, false);
  assert.equal(document.getElementById("modelBudgetPanel").hidden, false);
  assert.ok(
    document
      .getElementById("modelBudgetPanel")
      .closest(".model-console.is-editing"),
  );
  originalBudgetForm.querySelector("input").value = "17";
  const field = document.querySelector("[data-profile=simple]");
  field.querySelector("[name=model_name]").value = "changed-model";
  field
    .querySelector("[name=model_name]")
    .dispatchEvent(new w.Event("input", { bubbles: true }));
  document.getElementById("backToModels").click();
  assert.equal(document.getElementById("modelConnectionEditor").hidden, true);
  assert.equal(document.getElementById("modelBudgetPanel").hidden, true);
  document.getElementById("profile-tab-complex").click();
  assert.equal(document.getElementById("modelBudgetPanel").hidden, false);
  assert.equal(originalBudgetForm.querySelector("input").value, "17");
  assert.equal(document.getElementById("profile-panel-complex").hidden, false);
  assert.equal(document.getElementById("profile-panel-simple").hidden, true);
  document
    .getElementById("modelConnectionEditor")
    .dispatchEvent(
      new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
  assert.equal(document.getElementById("modelConnectionList").hidden, false);
  document.getElementById("profile-tab-simple").click();
  assert.equal(document.getElementById("profile-panel-simple").hidden, false);
  assert.equal(field.querySelector("[name=model_name]").value, "changed-model");
  document.getElementById("backToModels").click();
  document.getElementById("modelRouterEnabled").click();
  assert.deepEqual(visibleRoles(), ["embedding", "default"]);
  document.getElementById("modelRouterEnabled").click();
  document.getElementById("profile-tab-simple").click();
  assert.equal(field.querySelector("[name=model_name]").value, "changed-model");
  assert.equal(
    document.querySelector('[data-model-caption="simple"]').textContent,
    "changed-model",
  );
  assert.match(
    document.getElementById("modelDraftStatus").textContent,
    /未保存/,
  );
  const router = document.getElementById("modelRouterEnabled");
  router.checked = false;
  router.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.match(
    document.getElementById("modelRoutingPath").textContent,
    /默认模型/,
  );
  const action = field.querySelector("[name=key_action]");
  field.querySelector('[data-key-action="clear"]').click();
  assert.equal(action.value, "clear");
  field.querySelector('[data-key-action="inherit"]').click();
  assert.equal(action.value, "inherit");
  assert.equal(field.querySelector('[data-key-action="keep"]'), null);
  field.querySelector("[name=api_key]").value = "unit-private-key";
  field
    .querySelector("[name=api_key]")
    .dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.equal(action.value, "set");
  document
    .getElementById("modelSettingsForm")
    .dispatchEvent(new w.Event("submit", { cancelable: true }));
  await new Promise((r) => setTimeout(r, 5));
  const save = calls.filter(
    (c) => c.url === "/api/settings/models" && c.options.method === "POST",
  )[0];
  const data = JSON.parse(save.options.body);
  assert.equal(save.options.headers["X-Config-Token"], "unit-edit-token");
  assert.equal(data.profiles.simple.api_key, "unit-private-key");
  assert.equal(data.router_enabled, false);
  assert.equal(data.profiles.default.key_action, "keep");
  assert.equal("api_key" in data.profiles.default, false);
  assert.equal(calls.filter((c) => c.url.endsWith("/unlock")).length, 1);
  assert.equal(document.getElementById("modelConnectionList").hidden, false);
  assert.equal(document.getElementById("modelConnectionEditor").hidden, true);
  assert.equal(document.getElementById("modelBudgetPanel").hidden, true);
  assert.equal(document.getElementById("budgetForm"), originalBudgetForm);
  assert.equal(originalBudgetForm.querySelector("input").value, "17");
  document.dispatchEvent(new w.CustomEvent("research:edit-budget"));
  assert.equal(document.getElementById("modelBudgetPanel").hidden, false);
  assert.equal(document.getElementById("profile-panel-default").hidden, false);
  document.getElementById("saveBudget").click();
  assert.equal(budgetSaved, 1);
  assert.equal(localStorage.length, 0);
  assert.equal(document.querySelector("[name=api_key]").value, "*****************");
  assert.equal(document.getElementById("saveModels").disabled, true);
  assert.equal(document.body.textContent.includes("unit-private-key"), false);
  assert.equal(document.querySelector("[data-profile=simple]").disabled, false);
  document.getElementById("profile-tab-simple").click();
  document.querySelector("[data-profile=simple] [name=model_name]").value =
    "discard-me";
  document
    .querySelector("[data-profile=simple] [name=model_name]")
    .dispatchEvent(new w.Event("input", { bubbles: true }));
  location.hash = "#workspace";
  w.dispatchEvent(new w.Event("hashchange"));
  location.hash = "#settings";
  await new Promise((resolve) => setTimeout(resolve, 5));
  document.getElementById("profile-tab-simple").click();
  assert.equal(
    document.querySelector("[data-profile=simple] [name=model_name]").value,
    "simple",
  );
  failSave = true;
  const retryKey = document.querySelector(
    "[data-profile=simple] [name=api_key]",
  );
  retryKey.value = "unit-failed-private-key";
  retryKey.dispatchEvent(new w.Event("input", { bubbles: true }));
  const form = document.getElementById("modelSettingsForm");
  form.dispatchEvent(new w.Event("submit", { cancelable: true }));
  form.dispatchEvent(new w.Event("submit", { cancelable: true }));
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(retryKey.value, "");
  assert.equal(document.getElementById("saveModels").disabled, false);
  assert.equal(calls.filter((c) => c.url.endsWith("/unlock")).length, 2);
  const callCount = calls.length;
  form.dispatchEvent(new w.Event("submit", { cancelable: true }));
  assert.match(
    document.getElementById("modelSettingsStatus").textContent,
    /重新输入/,
  );
  assert.equal(calls.length, callCount);
  dom.window.close();
});
