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
};

const HISTORY_KEY = "stroke-companion:thread:v1";
const HISTORY_LIMIT = 50;

let ready = false;
let activeRequest = null;
let answerSequence = 0;
// Another tab changed the thread while this tab was busy; redraw once the request ends.
let pendingSync = false;
// Bumped on every reset so saves queued before it are dropped.
let historyGeneration = 0;

// Saved entries are { id, createdAt, question, payload }; payload stays null until an answer arrives.
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

function loadThread() {
  try {
    const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(stored)) return [];
    return stored
      .filter((entry) => entry && typeof entry.id === "string" && typeof entry.question === "string" && entry.question.trim())
      .map((entry) => ({
        id: entry.id,
        createdAt: Number(entry.createdAt) || 0,
        question: entry.question,
        payload: entry.payload && typeof entry.payload === "object" ? entry.payload : null,
      }))
      .slice(-HISTORY_LIMIT);
  } catch {
    return [];
  }
}

function writeThread(entries) {
  while (true) {
    try {
      if (entries.length) localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
      else localStorage.removeItem(HISTORY_KEY);
      return;
    } catch (error) {
      // Drop the oldest exchanges when storage is full; give up if storage is unavailable.
      if (error?.name !== "QuotaExceededError" || entries.length <= 1) return;
      entries = entries.slice(1);
    }
  }
}

// Serialize read-modify-write cycles across tabs where the Web Locks API is available.
function withHistoryLock(callback) {
  if (navigator.locks?.request) navigator.locks.request(HISTORY_KEY, callback).catch(() => {});
  else callback();
}

// Merge into the stored thread so exchanges saved by other tabs are kept.
function saveEntry(entry) {
  const generation = historyGeneration;
  const saved = { id: entry.id, createdAt: entry.createdAt, question: entry.question, payload: entry.payload };
  withHistoryLock(() => {
    if (generation !== historyGeneration) return;
    const entries = loadThread().filter((stored) => stored.id !== saved.id);
    entries.push(saved);
    entries.sort((a, b) => a.createdAt - b.createdAt);
    writeThread(entries.slice(-HISTORY_LIMIT));
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
    entry = { id: newEntryId(), createdAt: Date.now(), question, payload: null };
    articleEntries.set(article, entry);
    saveEntry(entry);
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
    // The thread was reset while waiting ("Start fresh" or another tab); drop the result.
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
  const entries = loadThread();
  ui.messages.replaceChildren();
  ui.messages.hidden = !entries.length;
  ui.welcome.hidden = Boolean(entries.length);
  if (!entries.length) return;
  for (const entry of entries) {
    appendQuestion(entry.question);
    const article = createAnswer();
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

// When following another tab's reset, leave storage alone so exchanges saved since are kept.
function startFresh(clearStorage = true) {
  activeRequest?.abort();
  activeRequest = null;
  pendingSync = false;
  historyGeneration++;
  if (clearStorage) withHistoryLock(() => writeThread([]));
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

document.querySelector("#new-session").addEventListener("click", () => {
  startFresh();
  ui.question.focus();
});

// Follow changes made in other tabs; a reset there also stops this tab's pending answer.
window.addEventListener("storage", (event) => {
  // key is null when another tab called localStorage.clear().
  if (event.key !== HISTORY_KEY && event.key !== null) return;
  if (event.key === null || event.newValue === null) startFresh(false);
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

renderThread();
checkAvailability();
