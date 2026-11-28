import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { updateStreamArticle } from "../../web/lib/stream-dom.js";

test("incremental text retains paragraph, text node, cursor and previous messages", () => {
  const dom = new JSDOM(
    '<main><article id="old">history</article><article id="live"><div class="message-body"><div data-stream-output></div><span class="stream-cursor"></span><div class="loading-dots"></div></div></article></main>',
  );
  const d = dom.window.document,
    article = d.getElementById("live"),
    old = d.getElementById("old"),
    cursor = d.querySelector(".stream-cursor");
  updateStreamArticle(article, { content: "Hello", reasoning: "" });
  const paragraph = article.querySelector("p"),
    text = paragraph.firstChild;
  updateStreamArticle(article, { content: "Hello world", reasoning: "" });
  assert.equal(article.querySelector("p"), paragraph);
  assert.equal(paragraph.firstChild, text);
  assert.equal(text.data, "Hello world");
  assert.equal(d.querySelector(".stream-cursor"), cursor);
  assert.equal(d.getElementById("old"), old);
  assert.equal(d.querySelector(".loading-dots"), null);
  dom.window.close();
});
test("code grows safely and provider reasoning expansion survives updates", () => {
  const dom = new JSDOM(
    '<article><div class="message-body"><div data-stream-output></div></div></article>',
  );
  const article = dom.window.document.querySelector("article");
  updateStreamArticle(article, {
    content: "```js\nconst a = 1;",
    reasoning: "First",
  });
  const details = article.querySelector("details");
  details.open = true;
  updateStreamArticle(article, {
    content: '```js\nconst a = 1;\nconst b = "<script>";\n```',
    reasoning: "First and second",
  });
  assert.equal(article.querySelector("details"), details);
  assert.equal(details.open, true);
  assert.match(article.querySelector("code").textContent, /const b/);
  assert.equal(article.querySelector("script"), null);
  dom.window.close();
});
