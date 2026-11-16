// Optional browser regression tests. Install playwright outside the repo, then run:
// RUN_BROWSER_TESTS=1 NODE_PATH=/path/to/node_modules node --test tests/test_chat_history.cjs
// The app must be running at CHAT_TEST_URL (default http://127.0.0.1:8000).
const { describe, test, before, after } = require("node:test");
const assert = require("node:assert/strict");

const KEY = "stroke-companion:chats:v2";
const LEGACY_KEY = "stroke-companion:thread:v1";
const baseURL = process.env.CHAT_TEST_URL || "http://127.0.0.1:8000";
const answer = { answer: "A saved answer about recovery.", citations: [], generation_model: "test" };

describe("conversation sidebar", { skip: process.env.RUN_BROWSER_TESTS !== "1" }, () => {
  let browser;
  before(async () => {
    const { chromium } = require("playwright");
    browser = await chromium.launch({
      executablePath: process.env.CHROME_PATH || (process.platform === "darwin" ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : undefined),
      headless: true,
    });
  });
  after(async () => { await browser?.close(); });

  async function setup(options = {}) {
    const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, ...options });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await context.route("**/status", (route) => route.fulfill({ json: { ready: true } }));
    await context.route("**/ask", (route) => route.fulfill({ json: answer }));
    await page.goto(baseURL);
    await page.waitForFunction(() => document.querySelector("#composer-status").textContent === "Ready for your question");
    return { context, page, errors };
  }

  async function ask(page, question, persisted = true) {
    await page.locator("#question").fill(question);
    await page.locator("#send").click();
    await page.waitForFunction(() => document.querySelector("#composer-status").textContent === "Answer ready");
    if (persisted) await page.waitForFunction((key) => JSON.parse(localStorage.getItem(key) || "[]").some((chat) => chat.entries.some((entry) => entry.payload?.answer)), KEY);
  }

  test("new chats preserve conversations; selection, follow-ups, search and reload work", async () => {
    const { context, page, errors } = await setup();
    try {
      await ask(page, "First recovery question");
      await page.locator("#new-session").click();
      assert.equal(await page.locator("#welcome").isVisible(), true);
      await page.locator("#close-sidebar").click();
      assert.equal(await page.locator("#chat-sidebar").evaluate((el) => el.inert), true);
      await page.locator("#toggle-sidebar").click();
      await ask(page, "Second nutrition question");
      assert.equal(await page.locator(".history-chat").count(), 2);
      await page.getByRole("button", { name: "First recovery question", exact: true }).click();
      assert.equal(await page.locator(".question-message").textContent(), "First recovery question");
      await ask(page, "A follow-up about exercise");
      assert.equal(await page.locator(".question-message").count(), 2);
      await page.reload();
      await page.locator(".question-message").nth(1).waitFor();
      assert.equal(await page.locator(".question-message").count(), 2);
      await page.locator("#history-search").fill("exercise");
      assert.equal(await page.locator(".history-chat").count(), 1);
      await page.locator("#history-search").fill("not-in-any-chat");
      assert.match(await page.locator("#chat-history").textContent(), /No chats found/);
      await page.locator("#history-search").fill("");
      await page.locator(".history-row.active").hover();
      await page.locator(".history-row.active .history-delete").click();
      await page.waitForFunction(() => document.querySelectorAll(".history-chat").length === 1);
      assert.equal(await page.locator("#welcome").isVisible(), true);
      await page.reload();
      await page.locator(".history-chat").waitFor();
      assert.equal(await page.locator(".history-chat").count(), 1);
      assert.deepEqual(errors, []);
      if (process.env.CHAT_SCREENSHOT) await page.screenshot({ path: process.env.CHAT_SCREENSHOT, fullPage: true });
    } finally { await context.close(); }
  });

  test("migrates the existing single-thread history without losing answers", async () => {
    const { context, page, errors } = await setup();
    try {
      await page.evaluate(({ key, legacy, payload }) => {
        localStorage.removeItem(key);
        sessionStorage.clear();
        localStorage.setItem(legacy, JSON.stringify([{ id: "old", createdAt: Date.now(), question: "My existing chat", payload }]));
      }, { key: KEY, legacy: LEGACY_KEY, payload: answer });
      await page.reload();
      await page.locator(".answer-body").waitFor();
      assert.match(await page.locator(".answer-body").textContent(), /saved answer/);
      assert.equal(await page.locator(".history-chat").textContent(), "My existing chat");
      assert.equal(await page.evaluate((key) => localStorage.getItem(key), LEGACY_KEY), null);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  test("switching chats during an answer keeps the unfinished exchange in its original chat", async () => {
    const { context, page, errors } = await setup();
    try {
      await ask(page, "Completed conversation");
      await page.locator("#new-session").click();
      let finish;
      const waiting = new Promise((resolve) => { finish = resolve; });
      await context.route("**/ask", async (route) => { await waiting; await route.fulfill({ json: answer }).catch(() => {}); });
      await page.locator("#question").fill("Slow question");
      await page.locator("#send").click();
      await page.getByRole("button", { name: "Slow question", exact: true }).waitFor();
      await page.getByRole("button", { name: "Completed conversation", exact: true }).click();
      finish();
      assert.equal(await page.locator(".question-message").textContent(), "Completed conversation");
      await page.getByRole("button", { name: "Slow question", exact: true }).click();
      assert.match(await page.locator(".error-message").textContent(), /did not finish/);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  test("other tabs update history and deletion never resurrects a pending chat", async () => {
    const { context, page, errors } = await setup();
    try {
      await ask(page, "Shared chat");
      const other = await context.newPage();
      await other.goto(baseURL);
      await other.locator(".history-chat").waitFor();
      await ask(page, "Follow-up in first tab");
      await other.waitForFunction(() => document.querySelectorAll(".question-message").length === 2);
      let finish;
      const waiting = new Promise((resolve) => { finish = resolve; });
      await context.route("**/ask", async (route) => { await waiting; await route.fulfill({ json: answer }).catch(() => {}); });
      await page.locator("#question").fill("Pending answer before deletion");
      await page.locator("#send").click();
      await other.waitForFunction(() => document.querySelectorAll(".question-message").length === 3);
      await other.locator(".history-row").hover();
      await other.locator(".history-delete").click();
      await page.locator("#welcome").waitFor();
      finish();
      // Wait through the same lock used by late saves before checking persistence.
      await page.evaluate((key) => navigator.locks.request(key, () => {}), KEY);
      assert.equal(await page.locator(".history-chat").count(), 0);
      assert.equal(await page.evaluate((key) => JSON.parse(localStorage.getItem(key)).length, KEY), 0);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  test("mobile drawer closes on Escape and selection without horizontal overflow", async () => {
    const { context, page, errors } = await setup({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    try {
      await ask(page, "Mobile conversation");
      await page.locator("#toggle-sidebar").click();
      assert.equal(await page.locator("#sidebar-backdrop").isVisible(), true);
      assert.equal(await page.locator("#workspace").evaluate((el) => el.inert), true);
      await page.keyboard.press("Escape");
      assert.equal(await page.locator("#sidebar-backdrop").isVisible(), false);
      await page.locator("#toggle-sidebar").click();
      await page.locator("#new-session").click();
      await page.locator("#toggle-sidebar").click();
      await page.getByRole("button", { name: "Mobile conversation", exact: true }).click();
      assert.equal(await page.locator("#sidebar-backdrop").isVisible(), false);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.setViewportSize({ width: 320, height: 640 });
      await page.locator("#toggle-sidebar").click();
      assert.equal(await page.locator("#new-session span").isVisible(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  test("storage failures show a notice and keep chats usable in this session", async () => {
    const { context, page, errors } = await setup();
    try {
      await page.evaluate(() => { Storage.prototype.setItem = () => { throw new DOMException("Storage full", "QuotaExceededError"); }; });
      await ask(page, "A question with full storage", false);
      await page.waitForFunction(() => document.querySelectorAll(".history-chat").length === 1);
      assert.match(await page.locator("#history-notice").textContent(), /lost when you leave/);
      await page.locator("#new-session").click();
      await page.locator(".history-chat").click();
      assert.match(await page.locator(".answer-body").textContent(), /saved answer/);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });
});
