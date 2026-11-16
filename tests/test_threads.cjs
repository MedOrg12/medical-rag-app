const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const context = { window: {} };
// Same realm, so arrays from the store compare equal to array literals.
new Function("window", fs.readFileSync(path.join(__dirname, "../static/threads.js"), "utf8"))(context.window);
const store = context.window.ThreadStore;

function memoryStorage(initial = {}, quota = Infinity) {
  const items = new Map(Object.entries(initial));
  return {
    items,
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem(key, value) {
      if (value.length > quota) throw Object.assign(new Error("full"), { name: "QuotaExceededError" });
      items.set(key, value);
    },
    removeItem: (key) => items.delete(key),
  };
}

const entry = (id, question, createdAt, payload = null) => ({ id, question, createdAt, payload });

test("conversations are kept separately and listed newest first", () => {
  const storage = memoryStorage();
  store.saveEntry(storage, "a", entry("1", "What should I eat after a stroke?", 1), { create: true, now: 10 });
  store.saveEntry(storage, "b", entry("2", "What is dysphagia?", 2), { create: true, now: 20 });
  store.saveEntry(storage, "a", entry("1", "What should I eat after a stroke?", 1, { answer: "Vegetables." }), { now: 30 });
  const threads = store.read(storage);
  assert.deepEqual(threads.map((thread) => thread.id), ["a", "b"]);
  assert.equal(threads[0].title, "What should I eat after a stroke?");
  assert.equal(threads[0].entries.length, 1);
  assert.equal(threads[0].entries[0].payload.answer, "Vegetables.");
  assert.equal(threads[1].entries[0].question, "What is dysphagia?");
});

test("an answer for a deleted conversation does not recreate it", () => {
  const storage = memoryStorage();
  store.saveEntry(storage, "a", entry("1", "Question", 1), { create: true });
  store.remove(storage, "a");
  assert.equal(store.saveEntry(storage, "a", entry("1", "Question", 1, { answer: "Late" })), false);
  assert.equal(store.read(storage).length, 0);
  assert.equal(storage.getItem(store.KEY), null);
});

test("the single saved conversation from before is migrated and the old key removed", () => {
  const legacy = JSON.stringify([entry("1", "Old question", 5, { answer: "Old answer" })]);
  const storage = memoryStorage({ [store.LEGACY_KEY]: legacy });
  const [thread] = store.read(storage);
  assert.equal(thread.title, "Old question");
  assert.equal(store.read(storage)[0].id, thread.id, "the migrated id is stable before the first write");
  store.saveEntry(storage, thread.id, entry("2", "New question", 6), { now: 7 });
  assert.equal(storage.getItem(store.LEGACY_KEY), null);
  assert.deepEqual(store.read(storage)[0].entries.map((item) => item.id), ["1", "2"]);
});

test("a full storage drops other conversations before the one being saved", () => {
  const storage = memoryStorage();
  store.saveEntry(storage, "old", entry("1", "x".repeat(400), 1), { create: true, now: 1 });
  storage.setItem = ((setItem) => (key, value) => {
    if (value.length > 600) throw Object.assign(new Error("full"), { name: "QuotaExceededError" });
    setItem(key, value);
  })(storage.setItem);
  assert.equal(store.saveEntry(storage, "new", entry("2", "y".repeat(300), 2), { create: true, now: 2 }), true);
  assert.deepEqual(store.read(storage).map((thread) => thread.id), ["new"]);
});

test("damaged storage reads as no conversations and long titles are shortened", () => {
  assert.equal(store.read(memoryStorage({ [store.KEY]: "{not json" })).length, 0);
  assert.equal(store.read(memoryStorage({ [store.KEY]: JSON.stringify([{ id: "bad id!", entries: [entry("1", "q", 1)] }]) })).length, 0);
  const title = store.titleFor(`  ${"word ".repeat(30)}`);
  assert.ok(title.length <= 60);
  assert.ok(title.endsWith("…"));
});
