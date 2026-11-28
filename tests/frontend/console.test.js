import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { budgetSamples } from "../../web/components/budget-chart.js";
import { readFileSync } from "node:fs";

test("budget chart projects only recorded numeric data and never invents costs", () => {
  const events = [
    { name: "llm.stream.delta", data: { used: { tokens: 999 } } },
    {
      name: "budget.updated",
      timestamp: 1,
      data: { used: { tokens: 20, cost: 0.01 }, limits: {} },
    },
    {
      name: "budget.updated",
      timestamp: 2,
      data: {
        used: { tokens: 30, cost: 0.02 },
        limits: { input_price_per_million: 1, output_price_per_million: 2 },
      },
    },
  ];
  assert.deepEqual(budgetSamples(events, "tokens"), [
    [1000, 20],
    [2000, 30],
  ]);
  assert.deepEqual(budgetSamples(events, "cost"), [[2000, 0.02]]);
  assert.deepEqual(budgetSamples([], "tokens"), []);
});

test("light-only appearance overrides an older saved dark preference", () => {
  const dom = new JSDOM(
    '<html data-theme="dark"><head></head><body></body></html>',
    { url: "http://localhost", runScripts: "outside-only" },
  );
  dom.window.localStorage.setItem("research-console-theme", "dark");
  dom.window.eval(
    readFileSync(
      new URL("../../web/lib/appearance-init.js", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(dom.window.document.documentElement.dataset.theme, "light");
  assert.equal(dom.window.localStorage.getItem("research-console-theme"), null);
  dom.window.close();
});
