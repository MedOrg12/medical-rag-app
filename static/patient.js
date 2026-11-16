"use strict";

const ui = {
  form: document.querySelector("#ask-form"),
  question: document.querySelector("#question"),
  send: document.querySelector("#send"),
  stop: document.querySelector("#stop"),
  status: document.querySelector("#composer-status"),
  welcome: document.querySelector("#welcome"),
  messages: document.querySelector("#messages"),
  availability: document.querySelector("#availability"),
  availabilityMessage: document.querySelector("#availability-message"),
  checkStatus: document.querySelector("#check-status"),
  newSession: document.querySelector("#new-session"),
  showThreads: document.querySelector("#show-threads"),
  threadsDialog: document.querySelector("#threads-dialog"),
  threadList: document.querySelector("#thread-list"),
  threadsEmpty: document.querySelector("#threads-empty"),
  deleteAll: document.querySelector("#delete-all"),
};

// The conversation a tab shows survives a reload of that tab; other tabs keep their own.
const ACTIVE_KEY = "stroke-companion:active-thread";

let ready = false;
let activeRequest = null;
let answerSequence = 0;
// Another tab changed the open conversation while this tab was busy; redraw once the request ends.
let pendingSync = false;
// null until the first question of a new conversation.
let activeThreadId = null;
// Set once the open conversation is in storage, so its absence there means it was deleted.
let activeThreadSaved = false;

// Saved entries are { id, createdAt, question, payload }; payload stays null until an answer arrives.
// In memory each entry also carries the threadId of its conversation.
const articleEntries = new WeakMap();

function icon(name, className = "") {
  return `<svg class="${className}" aria-hidden="true"><use href="/static/icons.svg#${name}"></use></svg>`;
}

function updateControls() {
  const busy = Boolean(activeRequest);
  ui.send.hidden = busy;
  ui.stop.hidden = !busy;
  ui.send.disabled = !ready || !ui.question.value.trim() || busy;
  ui.messages.setAttribute("aria-busy", String(busy));
}

function resizeQuestion() {
  ui.question.style.height = "auto";
  ui.question.style.height = `${Math.min(ui.question.scrollHeight, 200)}px`;
  updateControls();
}

// localStorage throws in some private modes; treat that as nothing saved.
function storage() {
  try {
    return localStorage;
  } catch {
    return null;
  }
}

function loadThreads() {
  const store = storage();
  return store ? ThreadStore.read(store) : [];
}

function findThread(id) {
  return id ? loadThreads().find((thread) => thread.id === id) || null : null;
}

// Serialize read-modify-write cycles across tabs where the Web Locks API is available.
function withHistoryLock(callback) {
  if (navigator.locks?.request) navigator.locks.request(ThreadStore.KEY, callback).catch(() => {});
  else callback();
}

function setActiveThread(id, saved = Boolean(id)) {
  activeThreadId = id;
  activeThreadSaved = saved;
  try {
    if (id) sessionStorage.setItem(ACTIVE_KEY, id);
    else sessionStorage.removeItem(ACTIVE_KEY);
  } catch {
    // The open conversation is just not remembered across reloads.
  }
}

// Conversations this tab has created; a later save must not create them again after a deletion.
const createdThreads = new Set();

// Merge into the stored conversation so exchanges saved by other tabs are kept.
function saveEntry(entry, create = false) {
  withHistoryLock(() => {
    const store = storage();
    if (!store) return;
    const saved = ThreadStore.saveEntry(store, entry.threadId, entry, { create: create && !createdThreads.has(entry.threadId) });
    if (saved) createdThreads.add(entry.threadId);
    if (saved && entry.threadId === activeThreadId) activeThreadSaved = true;
    if (ui.threadsDialog.open) renderThreadList();
  });
}

function newEntryId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function checkAvailability() {
  ui.checkStatus.disabled = true;
  ui.status.textContent = "Checking availability...";
  try {
    const response = await fetch("/status");
    if (!response.ok) throw new Error("Unavailable");
    const payload = await response.json();
    ready = payload.ready === true;
    ui.availability.hidden = ready;
    ui.availabilityMessage.textContent = "Answers are not available yet. The study library is still being prepared.";
    ui.status.textContent = ready ? "Ready for your question" : "Study library is not ready yet";
  } catch {
    ready = false;
    ui.availability.hidden = false;
    ui.availabilityMessage.textContent = "We cannot connect right now. Please try again in a moment.";
    ui.status.textContent = "Temporarily unavailable";
  } finally {
    ui.checkStatus.disabled = false;
    updateControls();
  }
}

function appendQuestion(question) {
  const user = document.createElement("p");
  user.className = "question-message";
  user.textContent = question;
  ui.messages.append(user);
}

function renderError(article, entry, text) {
  const body = article.querySelector(".answer-body");
  body.replaceChildren();
  const message = document.createElement("p");
  message.className = "error-message";
  message.textContent = text;
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "quiet-button";
  retry.innerHTML = `${icon("rotate-ccw")}<span>Try again</span>`;
  retry.addEventListener("click", () => ask(entry.question, article));
  body.append(message, retry);
}

function createAnswer() {
  const article = document.createElement("article");
  article.className = "answer-message";
  article.id = `answer-${++answerSequence}`;
  article.innerHTML = `<div class="answer-label">${icon("heart-pulse")}<span>Stroke Companion</span></div>
    <div class="answer-body"><p class="pending"><span class="spinner" aria-hidden="true"></span>Looking through the stroke literature...</p></div>`;
  ui.messages.append(article);
  return article;
}

function renderAnswer(article, payload) {
  const citations = (payload.citations || []).filter((citation) => Number.isInteger(citation.id) && citation.id > 0);
  const otherEvidence = payload.retrieved_evidence || [];
  const rawAnswer = String(payload.answer || "");
  // Added by the backend when the language model was unreachable.
  const fallback = rawAnswer.includes("Generation backend was unavailable, so this answer uses extractive retrieval.");
  let answer = rawAnswer
    .replace(/^Generation backend was unavailable, so this answer uses extractive retrieval\..*$/gm, "")
    .replace(/^Backend error:.*$/gm, "")
    .trim();
  if (payload.safety_notice && answer.endsWith(payload.safety_notice)) {
    answer = answer.slice(0, -payload.safety_notice.length).trim();
  }
  article.querySelector(".answer-body").innerHTML = EvidenceUI.answer(answer || "No answer was returned. Please try asking again.", citations, `${article.id}-source`)
    + EvidenceUI.warnings(payload.citation_validation)
    + EvidenceUI.conflicts(payload.evidence_conflicts || [], `${article.id}-source`);

  if (fallback || payload.generation_model === "extractive") {
    const note = document.createElement("p");
    note.className = "answer-note";
    note.textContent = fallback
      ? "The answer service is temporarily unavailable. These are excerpts from the study library."
      : "This answer contains excerpts from the study library.";
    article.append(note);
  } else if (!citations.length) {
    const note = document.createElement("p");
    note.className = "answer-note";
    note.textContent = otherEvidence.length ? "This answer has no cited sources. Related passages are listed separately." : "No supporting source was found in the study library.";
    article.append(note);
  }

  const tools = document.createElement("div");
  tools.className = "answer-tools";
  const groups = document.createElement("div");
  groups.className = "source-groups";
  for (const [items, label] of [[citations, "Sources cited in answer"], [otherEvidence, "Other retrieved passages"]]) {
    if (!items.length) continue;
    const details = document.createElement("details");
    details.className = "sources";
    details.innerHTML = `<summary>${icon("file-text")}<span>${label} (${items.length})</span>${icon("chevron-down", "chevron")}</summary>`;
    const list = document.createElement("div");
    list.className = "source-list";
    list.innerHTML = EvidenceUI.sources(items, `${article.id}-source`);
    details.append(list);
    groups.append(details);
  }
  tools.append(groups);
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "icon-button copy-button";
  copy.title = "Copy answer";
  copy.setAttribute("aria-label", "Copy answer");
  copy.innerHTML = icon("copy");
  copy.addEventListener("click", async () => {
    try {
      const sources = citations.map((citation) => `[${citation.id}] ${citation.title || citation.source}; ${citation.publisher || "publisher not recorded"}; ${citation.publication_year || "year not recorded"}${citation.page != null ? `; PDF page ${citation.page}` : ""}`).join("\n");
      await navigator.clipboard.writeText([answer, sources, payload.safety_notice].filter(Boolean).join("\n\n"));
      ui.status.textContent = "Answer copied";
    } catch {
      ui.status.textContent = "Could not copy. You can select the answer text instead.";
    }
  });
  tools.append(copy);
  article.append(tools);
}

async function ask(question, existingArticle = null) {
  if (activeRequest || !ready || !question.trim()) return;
  ui.welcome.hidden = true;
  ui.messages.hidden = false;
  if (!existingArticle) appendQuestion(question);
  const article = existingArticle || createAnswer();
  let entry = articleEntries.get(article);
  if (!entry) {
    if (!activeThreadId) setActiveThread(newEntryId(), false);
    entry = { id: newEntryId(), threadId: activeThreadId, createdAt: Date.now(), question, payload: null };
    articleEntries.set(article, entry);
    // Only a new conversation may be created, so a save queued behind a deletion elsewhere does not undo it.
    saveEntry(entry, !activeThreadSaved);
  }
  if (existingArticle) {
    if (ui.question.value.trim() === question) {
      ui.question.value = "";
      resizeQuestion();
    }
    article.querySelector(".answer-body").innerHTML = '<p class="pending"><span class="spinner" aria-hidden="true"></span>Looking through the stroke literature...</p>';
  }
  const controller = new AbortController();
  activeRequest = controller;
  ui.status.textContent = "Preparing your answer...";
  updateControls();
  article.scrollIntoView({ behavior: "smooth", block: "start" });
  let response;
  try {
    response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer_mode: "patient" }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("Request failed");
    const payload = await response.json();
    // The conversation was left or deleted while waiting; drop the result.
    if (activeRequest !== controller) return;
    renderAnswer(article, payload);
    entry.payload = payload;
    saveEntry(entry);
    ui.status.textContent = "Answer ready";
  } catch (error) {
    if (activeRequest !== controller) return;
    renderError(article, entry, error.name === "AbortError"
      ? "You stopped waiting for this answer."
      : response?.status === 409
        ? "The study library is not ready yet. Please try again later."
        : "We could not get an answer right now. Please try again.");
    ui.status.textContent = error.name === "AbortError" ? "Stopped" : "Answer unavailable";
    if (!ui.question.value) {
      ui.question.value = question;
      resizeQuestion();
    }
  } finally {
    if (activeRequest === controller) {
      activeRequest = null;
      updateControls();
      if (pendingSync) queueRenderThread();
    }
  }
}

function renderThread() {
  pendingSync = false;
  const thread = findThread(activeThreadId);
  if (!thread && activeThreadSaved) setActiveThread(null);
  const entries = thread ? thread.entries : [];
  ui.messages.replaceChildren();
  ui.messages.hidden = !entries.length;
  ui.welcome.hidden = Boolean(entries.length);
  if (!entries.length) return;
  for (const entry of entries) {
    appendQuestion(entry.question);
    const article = createAnswer();
    entry.threadId = thread.id;
    articleEntries.set(article, entry);
    try {
      if (!entry.payload) throw new Error("Unfinished answer");
      renderAnswer(article, entry.payload);
    } catch {
      entry.payload = null;
      renderError(article, entry, "This answer did not finish. Please try again.");
    }
  }
  ui.messages.lastElementChild.scrollIntoView({ block: "end" });
}

// Redraw after this tab's queued saves land, but never over an answer that is still loading.
function queueRenderThread() {
  pendingSync = true;
  withHistoryLock(() => {
    if (!activeRequest && pendingSync) renderThread();
  });
}

// Leaving a conversation stops its pending answer; the question stays saved and can be retried.
function leaveThread() {
  activeRequest?.abort();
  activeRequest = null;
  pendingSync = false;
}

function openThread(id) {
  leaveThread();
  setActiveThread(id);
  renderThread();
  ui.status.textContent = ready ? "Ready for your question" : "Temporarily unavailable";
  updateControls();
}

function formatUpdated(timestamp) {
  const date = new Date(timestamp);
  if (!timestamp || Number.isNaN(date.getTime())) return "";
  return new Date().toDateString() === date.toDateString()
    ? `Today, ${date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function renderThreadList() {
  const threads = loadThreads();
  // Keep keyboard focus on the same control when the list redraws.
  const focused = ui.threadList.contains(document.activeElement) ? document.activeElement : null;
  const focusSelector = focused?.dataset.threadId ? `[data-thread-id="${CSS.escape(focused.dataset.threadId)}"]`
    : focused?.dataset.deleteThread ? `[data-delete-thread="${CSS.escape(focused.dataset.deleteThread)}"]` : null;
  ui.threadList.replaceChildren();
  ui.threadList.hidden = !threads.length;
  ui.threadsEmpty.hidden = Boolean(threads.length);
  ui.deleteAll.hidden = !threads.length;
  for (const thread of threads) {
    const item = document.createElement("li");
    item.className = "thread-item";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "thread-open";
    open.dataset.threadId = thread.id;
    if (thread.id === activeThreadId) open.setAttribute("aria-current", "true");
    const title = document.createElement("span");
    title.className = "thread-title";
    title.textContent = thread.title;
    const meta = document.createElement("span");
    meta.className = "thread-meta";
    const count = thread.entries.length;
    meta.textContent = [formatUpdated(thread.updatedAt), `${count} ${count === 1 ? "question" : "questions"}`].filter(Boolean).join(" · ");
    open.append(title, meta);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-button thread-delete";
    remove.dataset.deleteThread = thread.id;
    remove.title = "Delete conversation";
    remove.setAttribute("aria-label", `Delete conversation: ${thread.title}`);
    remove.innerHTML = icon("trash-2");
    item.append(open, remove);
    ui.threadList.append(item);
  }
  if (!focused) return;
  const target = focusSelector && ui.threadList.querySelector(focusSelector);
  if (target) target.focus();
  else focusThreadList();
}

function focusThreadList() {
  (ui.threadList.querySelector('[aria-current="true"]') || ui.threadList.querySelector(".thread-open") || ui.threadsDialog.querySelector(".dialog-close")).focus();
}

// The open conversation may have been reopened while a deletion waited for the lock.
function leaveIfDeleted() {
  if (activeThreadSaved && !findThread(activeThreadId)) startNewChat();
}

function deleteThread(id) {
  if (id === activeThreadId) startNewChat();
  withHistoryLock(() => {
    const store = storage();
    if (store) ThreadStore.remove(store, id);
    leaveIfDeleted();
    if (!ui.threadsDialog.open) return;
    renderThreadList();
    focusThreadList();
  });
}

function startNewChat() {
  leaveThread();
  setActiveThread(null);
  ui.messages.replaceChildren();
  ui.messages.hidden = true;
  ui.welcome.hidden = false;
  ui.question.value = "";
  ui.status.textContent = ready ? "Ready for your question" : "Temporarily unavailable";
  resizeQuestion();
}

ui.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = ui.question.value.trim();
  if (!question || activeRequest || !ready) return;
  ui.question.value = "";
  resizeQuestion();
  ask(question);
});
ui.question.addEventListener("input", resizeQuestion);
ui.question.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!ui.send.disabled) ui.form.requestSubmit();
  }
});
ui.stop.addEventListener("click", () => activeRequest?.abort());
ui.checkStatus.addEventListener("click", checkAvailability);

ui.newSession.addEventListener("click", () => {
  startNewChat();
  ui.question.focus();
});

ui.showThreads.addEventListener("click", () => {
  renderThreadList();
  ui.threadsDialog.showModal();
  focusThreadList();
});

ui.threadsDialog.addEventListener("click", (event) => {
  // A click on the backdrop lands on the dialog element itself.
  if (event.target === ui.threadsDialog || event.target.closest(".dialog-close")) {
    ui.threadsDialog.close();
    return;
  }
  const open = event.target.closest("[data-thread-id]");
  if (open) {
    ui.threadsDialog.close();
    if (open.dataset.threadId !== activeThreadId) openThread(open.dataset.threadId);
    ui.question.focus();
    return;
  }
  const remove = event.target.closest("[data-delete-thread]");
  if (remove) deleteThread(remove.dataset.deleteThread);
});

ui.deleteAll.addEventListener("click", () => {
  if (!confirm("Delete all saved conversations from this browser?")) return;
  startNewChat();
  withHistoryLock(() => {
    const store = storage();
    if (store) ThreadStore.removeAll(store);
    leaveIfDeleted();
    renderThreadList();
    focusThreadList();
  });
});

// Follow changes made in other tabs; deleting the open conversation there also stops this tab's pending answer.
window.addEventListener("storage", (event) => {
  // key is null when another tab called localStorage.clear().
  if (event.key !== ThreadStore.KEY && event.key !== null) return;
  if (ui.threadsDialog.open) renderThreadList();
  if (!activeThreadId) return;
  if (activeThreadSaved && !findThread(activeThreadId)) startNewChat();
  else if (activeRequest) pendingSync = true;
  else queueRenderThread();
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    ui.question.value = button.dataset.question;
    resizeQuestion();
    ui.question.focus();
  });
});

ui.messages.addEventListener("click", (event) => {
  const button = event.target.closest("[data-source]");
  if (!button) return;
  const source = document.getElementById(button.dataset.source);
  if (!source) return;
  let details = source.closest("details");
  while (details) {
    details.open = true;
    details = details.parentElement.closest("details");
  }
  source.focus({ preventScroll: true });
  source.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

// Reopen this tab's conversation after a reload; a new tab opens the most recent one.
let restoredId = null;
try {
  restoredId = sessionStorage.getItem(ACTIVE_KEY);
} catch {
  // Fall back to the most recent conversation.
}
setActiveThread(findThread(restoredId)?.id || loadThreads()[0]?.id || null);
renderThread();
checkAvailability();
