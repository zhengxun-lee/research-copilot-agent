import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { mountModelSettings } from "../../web/components/model-settings.js";

test("eye reveals on demand, supports editing, and discards late responses and plaintext on exit", async () => {
  const dom = new JSDOM(
    '<div id="modelSettings"></div><p id="modelSettingsStatus"></p>',
    { url: "http://localhost/#settings" },
  );
  const w = dom.window;
  for (const name of [
    "window",
    "document",
    "location",
    "localStorage",
    "CustomEvent",
  ])
    globalThis[name] = name === "window" ? w : w[name];
  globalThis.addEventListener = w.addEventListener.bind(w);
  const view = {
    can_edit: true,
    revision: 0,
    router_enabled: false,
    profiles: Object.fromEntries(
      ["default", "simple", "complex", "embedding"].map((role) => [
        role,
        {
          model_name: role,
          base_url: "https://example.test/v1",
          key_configured: true,
          key_mode: "set",
          key_preview: "*****************",
        },
      ]),
    ),
  };
  const calls = [];
  let pending = null,
    slow = false;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith("/reveal") && slow)
      await new Promise((resolve) => {
        pending = resolve;
      });
    return new Response(
      JSON.stringify(
        url.endsWith("/unlock")
          ? { edit_token: "test-nonce" }
          : url.endsWith("/reveal")
            ? { api_key: "unit-saved-secret" }
            : view,
      ),
      { status: 200 },
    );
  };
  const flush = () => new Promise((r) => setTimeout(r, 5));
  mountModelSettings();
  await flush();
  document.getElementById("profile-tab-default").click();
  const field = document.querySelector("[data-profile=default]");
  const key = field.querySelector("[name=api_key]");
  const eye = field.querySelector("[data-toggle-key]");
  assert.equal(calls.length, 1);
  for (const name of ["model_name", "base_url", "api_key"]) {
    const input = field.querySelector(`[name=${name}]`);
    input.setSelectionRange(3, 3);
    input.focus();
    input.click();
    assert.equal(input.selectionStart, 3);
    assert.equal(input.selectionEnd, 3);
  }
  assert.equal(key.value, "*****************");
  assert.equal(field.querySelector("[name=key_action]").value, "keep");
  key.dispatchEvent(new w.InputEvent("beforeinput", {
    bubbles: true, inputType: "insertText", data: "x",
  }));
  assert.equal(key.value, "");
  assert.equal(key.type, "password");
  key.value = "replacement-key";
  key.dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.equal(field.querySelector("[name=key_action]").value, "set");
  const url = field.querySelector("[name=base_url]");
  url.value = "bad url";
  url.dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.equal(url.checkValidity(), false);
  url.value = "https://example.test/v1";
  url.dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.equal(url.checkValidity(), true);
  location.hash = "#workspace";
  w.dispatchEvent(new w.Event("hashchange"));
  location.hash = "#settings";
  await new Promise((resolve) => setTimeout(resolve, 5));
  document.getElementById("profile-tab-default").click();
  const get = (selector) =>
    document.querySelector("[data-profile=default] " + selector);
  get("[data-toggle-key]").click();
  await flush();
  assert.equal(get("[name=api_key]").type, "text");
  assert.equal(get("[name=api_key]").value, "unit-saved-secret");
  assert.equal(get("[name=key_action]").value, "keep");
  assert.equal(document.getElementById("saveModels").disabled, true);
  assert.equal(get("[data-toggle-key]").getAttribute("aria-pressed"), "true");
  get("[data-toggle-key]").click();
  assert.equal(get("[name=api_key]").type, "text");
  assert.equal(get("[name=api_key]").value, "*****************");
  get("[data-toggle-key]").click();
  await flush();
  get("[name=api_key]").value += "-edited";
  get("[name=api_key]").dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.equal(get("[name=key_action]").value, "set");
  get("[name=api_key]").setSelectionRange(0, 0);
  get("[name=api_key]").click();
  assert.equal(
    get("[name=api_key]").selectionStart,
    0,
  );
  document.getElementById("backToModels").click();
  assert.equal(get("[name=api_key]").type, "password");
  assert.equal(get("[name=api_key]").value, "unit-saved-secret-edited");
  document.getElementById("profile-tab-default").click();
  const count = calls.length;
  get("[data-toggle-key]").click();
  await flush();
  assert.equal(calls.length, count); // A typed draft needs no server fetch.
  location.hash = "#workspace";
  w.dispatchEvent(new w.Event("hashchange"));
  assert.equal(get("[name=api_key]").value, "*****************");
  assert.equal(get("[name=api_key]").type, "text");
  assert.equal(localStorage.length, 0);
  location.hash = "#settings";
  await flush();
  document.getElementById("profile-tab-default").click();
  slow = true;
  get("[data-toggle-key]").click();
  await flush();
  assert.ok(pending);
  document.getElementById("backToModels").click();
  pending();
  await flush();
  assert.equal(get("[name=api_key]").value, "*****************");
  assert.equal(get("[name=api_key]").type, "text");
  assert.equal(get("[data-toggle-key]").disabled, false);
  dom.window.close();
});
