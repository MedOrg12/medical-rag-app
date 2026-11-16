"use strict";

// Patient conversations, saved only in this browser. Nothing here is sent to the server.
// Stored value: [{ id, title, createdAt, updatedAt, entries: [{ id, createdAt, question, payload }] }].
(function (root) {
  const KEY = "stroke-companion:threads:v2";
  // The single conversation saved before multiple conversations existed.
  const LEGACY_KEY = "stroke-companion:thread:v1";
  const LEGACY_ID = "migrated-v1";
  const THREAD_LIMIT = 30;
  const ENTRY_LIMIT = 50;
  const TITLE_LENGTH = 60;
  const ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

  function titleFor(question) {
    const text = String(question).replace(/\s+/g, " ").trim();
    return text.length > TITLE_LENGTH ? `${text.slice(0, TITLE_LENGTH - 1).trimEnd()}…` : text;
  }

  function cleanEntries(list) {
    if (!Array.isArray(list)) return [];
    return list
      .filter((entry) => entry && typeof entry.id === "string" && typeof entry.question === "string" && entry.question.trim())
      .map((entry) => ({
        id: entry.id,
        createdAt: Number(entry.createdAt) || 0,
        question: entry.question,
        payload: entry.payload && typeof entry.payload === "object" ? entry.payload : null,
      }))
      .slice(-ENTRY_LIMIT);
  }

  function cleanThread(thread) {
    if (!thread || typeof thread.id !== "string" || !ID_PATTERN.test(thread.id)) return null;
    const entries = cleanEntries(thread.entries);
    if (!entries.length) return null;
    const createdAt = Number(thread.createdAt) || entries[0].createdAt;
    return {
      id: thread.id,
      title: typeof thread.title === "string" && thread.title.trim() ? thread.title : titleFor(entries[0].question),
      createdAt,
      updatedAt: Number(thread.updatedAt) || entries[entries.length - 1].createdAt || createdAt,
      entries,
    };
  }

  function parse(raw) {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  // Newest first. A browser that only has the old single conversation gets it as one thread;
  // the old key is removed on the next write.
  function read(storage) {
    let raw;
    let legacy = null;
    try {
      raw = storage.getItem(KEY);
      if (raw === null) legacy = storage.getItem(LEGACY_KEY);
    } catch {
      return [];
    }
    let threads;
    if (raw !== null) {
      const stored = parse(raw);
      threads = Array.isArray(stored) ? stored.map(cleanThread).filter(Boolean) : [];
    } else {
      const thread = legacy === null ? null : cleanThread({ id: LEGACY_ID, entries: parse(legacy) });
      threads = thread ? [thread] : [];
    }
    const seen = new Set();
    return threads
      .filter((thread) => !seen.has(thread.id) && seen.add(thread.id))
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }

  // When storage is full, drop the least recently used other threads, then the oldest
  // exchanges of the kept thread. Returns false if nothing could be written.
  function write(storage, threads, keepId = null) {
    threads = threads.slice().sort((a, b) => b.updatedAt - a.updatedAt);
    while (true) {
      try {
        if (threads.length) storage.setItem(KEY, JSON.stringify(threads));
        else storage.removeItem(KEY);
        storage.removeItem(LEGACY_KEY);
        return true;
      } catch (error) {
        if (error?.name !== "QuotaExceededError") return false;
        const dropIndex = threads.findLastIndex((thread) => thread.id !== keepId);
        if (dropIndex !== -1) {
          threads.splice(dropIndex, 1);
          continue;
        }
        const kept = threads[0];
        if (!kept || kept.entries.length <= 1) return false;
        threads = [{ ...kept, entries: kept.entries.slice(1) }];
      }
    }
  }

  // Adds or replaces an exchange. A missing thread is created only when `create` is set, so an
  // answer that arrives after its conversation was deleted does not bring it back.
  function saveEntry(storage, threadId, entry, { create = false, now = Date.now() } = {}) {
    const threads = read(storage);
    let thread = threads.find((item) => item.id === threadId);
    if (!thread) {
      if (!create) return false;
      thread = { id: threadId, title: titleFor(entry.question), createdAt: entry.createdAt, updatedAt: now, entries: [] };
      threads.unshift(thread);
    }
    const saved = { id: entry.id, createdAt: entry.createdAt, question: entry.question, payload: entry.payload ?? null };
    thread.entries = thread.entries.filter((item) => item.id !== saved.id);
    thread.entries.push(saved);
    thread.entries.sort((a, b) => a.createdAt - b.createdAt);
    thread.entries = thread.entries.slice(-ENTRY_LIMIT);
    thread.updatedAt = now;
    const kept = threads.sort((a, b) => b.updatedAt - a.updatedAt).slice(0, THREAD_LIMIT);
    return write(storage, kept, threadId);
  }

  function remove(storage, threadId) {
    return write(storage, read(storage).filter((thread) => thread.id !== threadId));
  }

  function removeAll(storage) {
    return write(storage, []);
  }

  root.ThreadStore = { KEY, LEGACY_KEY, THREAD_LIMIT, ENTRY_LIMIT, read, saveEntry, remove, removeAll, titleFor };
})(typeof window === "undefined" ? globalThis : window);
