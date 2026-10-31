"use strict";

/**
 * Patient chat page ("Stroke Companion").
 *
 * The page sends questions to `/ask` and renders the answers with their
 * citations. The conversation is saved to localStorage so it survives a page
 * refresh, and is kept in sync across tabs open on the same browser.
 *
 * Sections:
 *   1. State
 *   2. Small helpers
 *   3. Chat history storage (localStorage)
 *   4. Service availability
 *   5. Answer formatting (text to HTML)
 *   6. Rendering messages
 *   7. Asking questions
 *   8. Restoring and resetting the thread
 *   9. Event wiring and startup
 */

// ---------------------------------------------------------------------------
// 1. State
// ---------------------------------------------------------------------------

/** Elements from index.html that the script reads or updates. */
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

/** localStorage key for the saved thread. Bump the version if the entry format changes. */
const HISTORY_KEY = "stroke-companion:thread:v1";
/** Maximum number of question/answer exchanges kept in storage. */
const HISTORY_LIMIT = 50;

/** True once `/status` reports that the study library is ready to answer questions. */
let ready = false;
/** AbortController of the `/ask` request in flight, or null when idle. Only one request runs at a time. */
let activeRequest = null;
/** Counter used to give each answer article a unique DOM id (`answer-1`, `answer-2`, ...). */
let answerSequence = 0;
/** Set when another tab changed the thread while this tab was busy; the thread is redrawn once the request ends. */
let pendingSync = false;
/**
 * Increases on every reset ("Start fresh", or a reset in another tab).
 * Saves queued before a reset compare against it and are dropped, so they
 * cannot write cleared exchanges back into storage.
 */
let historyGeneration = 0;

/**
 * @typedef {object} ThreadEntry One question and its answer, as saved in localStorage.
 * @property {string} id Stable id, used to merge saves coming from several tabs.
 * @property {number} createdAt Creation time in ms since the epoch; sets the order of the thread.
 * @property {string} question The question the patient asked.
 * @property {object|null} payload The `/ask` response, or null while the answer is pending or after it failed.
 */

/**
 * Links each answer `<article>` to its ThreadEntry, so a retry or a finished
 * answer updates the right saved entry.
 * @type {WeakMap<HTMLElement, ThreadEntry>}
 */
const articleEntries = new WeakMap();

// ---------------------------------------------------------------------------
// 2. Small helpers
// ---------------------------------------------------------------------------

/**
 * Build the markup for an icon from the shared sprite sheet.
 * @param {string} name Symbol id in /static/icons.svg.
 * @param {string} [className] Optional CSS class for the <svg>.
 * @returns {string} SVG markup.
 */
function icon(name, className = "") {
  return `<svg class="${className}" aria-hidden="true"><use href="/static/icons.svg#${name}"></use></svg>`;
}

/**
 * Escape text so it can be inserted into HTML safely.
 * @param {unknown} text Any value; null and undefined become "".
 * @returns {string} Text with &, <, >, " and ' escaped.
 */
function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

/** Show Send or Stop, and enable Send only when a question can be sent. */
function updateControls() {
  const busy = Boolean(activeRequest);
  ui.send.hidden = busy;
  ui.stop.hidden = !busy;
  ui.send.disabled = !ready || !ui.question.value.trim() || busy;
  ui.messages.setAttribute("aria-busy", String(busy));
}

/** Grow the question box with its content (up to 200px), then refresh the buttons. */
function resizeQuestion() {
  ui.question.style.height = "auto";
  ui.question.style.height = `${Math.min(ui.question.scrollHeight, 200)}px`;
  updateControls();
}

// ---------------------------------------------------------------------------
// 3. Chat history storage (localStorage)
//
// localStorage is the shared copy of the thread for every tab. Each save
// re-reads storage and merges a single entry into it instead of writing this
// tab's view of the thread, so tabs don't overwrite each other's exchanges.
// ---------------------------------------------------------------------------

/**
 * Read the saved thread. Entries that are missing fields or are not valid
 * JSON are skipped, so bad stored data can't break the page.
 * @returns {ThreadEntry[]} Saved entries, oldest first, at most HISTORY_LIMIT.
 */
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
    // Storage is unavailable (e.g. blocked by privacy settings) or holds invalid JSON.
    return [];
  }
}

/**
 * Replace the saved thread. An empty list removes the key entirely.
 * @param {ThreadEntry[]} entries Entries to save, oldest first.
 */
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

/**
 * Run a read-modify-write on the saved thread while holding a lock shared by
 * every tab, so two tabs can't interleave their reads and writes. Browsers
 * without the Web Locks API run the callback right away. With the lock the
 * callback runs asynchronously, but locks are granted in request order.
 * @param {() => void} callback Function that reads and/or writes the thread.
 */
function withHistoryLock(callback) {
  if (navigator.locks?.request) navigator.locks.request(HISTORY_KEY, callback).catch(() => {});
  else callback();
}

/**
 * Insert or update one entry in the saved thread, keeping exchanges that
 * other tabs saved. The entry is copied now, so later changes to it need
 * another save. The save is skipped if the thread was reset before the lock
 * was granted.
 * @param {ThreadEntry} entry Entry to save.
 */
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

/**
 * Create an id for a new entry that won't clash with ids from other tabs.
 * @returns {string} A UUID, or a time-plus-random fallback where crypto.randomUUID is unavailable.
 */
function newEntryId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// ---------------------------------------------------------------------------
// 4. Service availability
// ---------------------------------------------------------------------------

/**
 * Ask `/status` whether the study library is ready, then update `ready`, the
 * availability banner, and the composer status line.
 */
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

// ---------------------------------------------------------------------------
// 5. Answer formatting (text to HTML)
//
// Answers arrive as plain text with light Markdown. Only headings, bullet and
// numbered lists, **bold**, and [n] citation markers are turned into HTML.
// Everything else is escaped.
// ---------------------------------------------------------------------------

/**
 * Format one line of answer text. Escape all supplied text first, then add
 * the small set of supported formatting tags: **bold**, and [n] markers that
 * match a known citation become buttons linking to that source.
 * @param {string} text Raw text.
 * @param {object[]} citations Citations for the answer; unknown [n] markers stay as plain text.
 * @param {string} answerId DOM id of the answer article, used to build source element ids.
 * @returns {string} Safe HTML.
 */
function inlineText(text, citations, answerId) {
  return escapeHtml(text)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(\d+)\]([.,;:]?)/g, (match, id, punctuation) => {
      if (!citations.some((citation) => String(citation.id) === id)) return match;
      // Keep trailing punctuation inside the span so it doesn't wrap onto its own line.
      return `<span class="citation-reference"><button type="button" class="citation-link" data-source="${answerId}-source-${id}" aria-label="Read source ${id}" title="Read source ${id}">[${id}]</button>${punctuation}</span>`;
    });
}

/**
 * Turn a whole answer into HTML blocks. Lines are grouped into paragraphs and
 * lists; blank lines and headings end the current block.
 * @param {string} text Answer text.
 * @param {object[]} citations Citations for the answer.
 * @param {string} answerId DOM id of the answer article.
 * @returns {string} Safe HTML.
 */
function answerHtml(text, citations, answerId) {
  const blocks = [];
  // Lines collected for the paragraph or list being built.
  let paragraph = [];
  let list = [];
  let listType = "";
  let listStart = 1;
  const inline = (value) => inlineText(value, citations, answerId);
  const flushParagraph = () => {
    if (paragraph.length) blocks.push(`<p>${inline(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (list.length) {
      blocks.push(`<${listType}${listType === "ol" ? ` start="${listStart}"` : ""}>${list.map((item) => `<li>${inline(item)}</li>`).join("")}</${listType}>`);
    }
    list = [];
    listType = "";
  };
  for (const line of String(text).split("\n")) {
    const trimmed = line.trim();
    const heading = trimmed.match(/^#{1,6}\s+(.+)$/);
    // item[1] holds the number for "1." items and is undefined for "-" or "*" bullets.
    const item = trimmed.match(/^(?:[-*]\s+|(\d+)\.\s+)(.+)$/);
    if (!trimmed || heading) {
      flushParagraph();
      flushList();
      if (heading) blocks.push(`<h2>${inline(heading[1])}</h2>`);
    } else if (item) {
      flushParagraph();
      const type = item[1] ? "ol" : "ul";
      if (listType !== type) flushList();
      // A numbered list keeps the model's first number, so it can continue after a break.
      if (!list.length) listStart = Number(item[1] || 1);
      listType = type;
      list.push(item[2]);
    } else {
      flushList();
      paragraph.push(trimmed);
    }
  }
  flushParagraph();
  flushList();
  return blocks.join("");
}

// ---------------------------------------------------------------------------
// 6. Rendering messages
// ---------------------------------------------------------------------------

/**
 * Add the patient's question bubble to the thread.
 * @param {string} question Question text (inserted as text, not HTML).
 */
function appendQuestion(question) {
  const user = document.createElement("p");
  user.className = "question-message";
  user.textContent = question;
  ui.messages.append(user);
}

/**
 * Replace an answer's body with an error message and a "Try again" button.
 * @param {HTMLElement} article Answer article to update.
 * @param {ThreadEntry} entry Entry for the article; its question is asked again on retry.
 * @param {string} text Message for the patient.
 */
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

/**
 * Add an empty answer article with a loading message to the thread.
 * @returns {HTMLElement} The new article.
 */
function createAnswer() {
  const article = document.createElement("article");
  article.className = "answer-message";
  article.id = `answer-${++answerSequence}`;
  article.innerHTML = `<div class="answer-label">${icon("heart-pulse")}<span>Stroke Companion</span></div>
    <div class="answer-body"><p class="pending"><span class="spinner" aria-hidden="true"></span>Looking through the stroke literature...</p></div>`;
  ui.messages.append(article);
  return article;
}

/**
 * Fill an answer article from an `/ask` response: the formatted answer, a
 * note when the answer is only excerpts or has no sources, the list of
 * sources, and a copy button. Backend diagnostic lines and the repeated safety
 * notice are removed from the visible text.
 * @param {HTMLElement} article Article created by createAnswer().
 * @param {object} payload `/ask` response (answer, citations, safety_notice, generation_model).
 * @throws {TypeError} If the payload has the wrong shape (for example, corrupted saved data).
 */
function renderAnswer(article, payload) {
  const citations = (payload.citations || []).filter((citation) => Number.isInteger(citation.id) && citation.id > 0);
  const rawAnswer = String(payload.answer || "");
  // The backend adds this line when the language model was unreachable and it fell back to raw excerpts.
  const fallback = rawAnswer.includes("Generation backend was unavailable, so this answer uses extractive retrieval.");
  let answer = rawAnswer
    .replace(/^Generation backend was unavailable, so this answer uses extractive retrieval\..*$/gm, "")
    .replace(/^Backend error:.*$/gm, "")
    .trim();
  if (payload.safety_notice && answer.endsWith(payload.safety_notice)) {
    answer = answer.slice(0, -payload.safety_notice.length).trim();
  }
  article.querySelector(".answer-body").innerHTML = answerHtml(answer || "No answer was returned. Please try asking again.", citations, article.id);

  // Tell the patient when the answer is only excerpts or has no supporting source.
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
    note.textContent = "No supporting source was found in the study library.";
    article.append(note);
  }

  // Collapsible source list. Item ids match the data-source values of the [n] buttons.
  const tools = document.createElement("div");
  tools.className = "answer-tools";
  if (citations.length) {
    const details = document.createElement("details");
    details.className = "sources";
    details.innerHTML = `<summary>${icon("file-text")}<span>View ${citations.length} source${citations.length === 1 ? "" : "s"}</span>${icon("chevron-down", "chevron")}</summary>`;
    const list = document.createElement("ol");
    list.className = "source-list";
    for (const citation of citations) {
      const item = document.createElement("li");
      item.id = `${article.id}-source-${citation.id}`;
      item.tabIndex = -1;
      const title = document.createElement("p");
      title.className = "source-title";
      title.textContent = `[${citation.id}] ${String(citation.source || "Stroke literature").replace(/\.pdf$/i, "").replace(/_/g, " ")}`;
      const page = document.createElement("span");
      page.className = "source-page";
      page.textContent = citation.page != null ? `Page ${citation.page}` : "Page not available";
      const excerpt = document.createElement("p");
      excerpt.className = "source-excerpt";
      excerpt.textContent = citation.excerpt || "";
      item.append(title, page, excerpt);
      list.append(item);
    }
    details.append(list);
    tools.append(details);
  }

  // Copy the answer, its sources, and the safety notice as plain text.
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "icon-button copy-button";
  copy.title = "Copy answer";
  copy.setAttribute("aria-label", "Copy answer");
  copy.innerHTML = icon("copy");
  copy.addEventListener("click", async () => {
    try {
      const sources = citations.map((citation) => `[${citation.id}] ${citation.source}${citation.page != null ? `, page ${citation.page}` : ""}`).join("\n");
      await navigator.clipboard.writeText([answer, sources, payload.safety_notice].filter(Boolean).join("\n\n"));
      ui.status.textContent = "Answer copied";
    } catch {
      ui.status.textContent = "Could not copy. You can select the answer text instead.";
    }
  });
  tools.append(copy);
  article.append(tools);
}

// ---------------------------------------------------------------------------
// 7. Asking questions
// ---------------------------------------------------------------------------

/**
 * Send a question to `/ask` and show the answer in the thread.
 *
 * A new question adds a question bubble and an answer article, and saves a
 * pending entry right away, so a refresh mid-answer still shows the question.
 * A retry passes the existing article, which is reused along with its entry.
 * The finished answer is saved to the same entry. Errors and Stop leave the
 * entry pending and show a retry button.
 *
 * @param {string} question Question text.
 * @param {HTMLElement|null} [existingArticle] Answer article to reuse when retrying.
 */
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
    // A failed request puts the question back in the composer; clear it again when retrying.
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
    // Put the question back in the composer so it is easy to resend or edit.
    if (!ui.question.value) {
      ui.question.value = question;
      resizeQuestion();
    }
  } finally {
    if (activeRequest === controller) {
      activeRequest = null;
      updateControls();
      // Another tab changed the thread while this request was running; show its changes now.
      if (pendingSync) renderThread();
    }
  }
}

// ---------------------------------------------------------------------------
// 8. Restoring and resetting the thread
// ---------------------------------------------------------------------------

/**
 * Rebuild the thread from storage. Runs on page load and whenever another
 * tab changes the saved thread. Entries without an answer, or with saved data
 * that can't be rendered, are shown with a retry button.
 */
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

/**
 * Clear the thread and show the welcome screen again. Any request in flight
 * is cancelled and saves still waiting for the lock are dropped.
 * @param {boolean} [clearStorage] Also delete the saved thread. Pass false when
 *   reacting to another tab's reset: storage is already empty, and writing it
 *   again could delete an exchange a third tab has saved since.
 */
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

// ---------------------------------------------------------------------------
// 9. Event wiring and startup
// ---------------------------------------------------------------------------

// Composer: submit with the Send button or Enter (Shift+Enter adds a new line).
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
// The storage event only fires in tabs other than the one that wrote the change.
window.addEventListener("storage", (event) => {
  // key is null when another tab called localStorage.clear().
  if (event.key !== HISTORY_KEY && event.key !== null) return;
  if (event.key === null || event.newValue === null) startFresh(false);
  // Redrawing would remove the answer that is still loading, so wait until it finishes.
  else if (activeRequest) pendingSync = true;
  else renderThread();
});

// Suggested questions on the welcome screen fill the composer without sending.
document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    ui.question.value = button.dataset.question;
    resizeQuestion();
    ui.question.focus();
  });
});

// Clicking an [n] citation opens the source list and moves focus to that source.
ui.messages.addEventListener("click", (event) => {
  const button = event.target.closest("[data-source]");
  if (!button) return;
  const source = document.getElementById(button.dataset.source);
  if (!source) return;
  source.closest("details").open = true;
  source.focus({ preventScroll: true });
  source.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

renderThread();
checkAvailability();
