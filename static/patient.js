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
  composerArea: document.querySelector("#composer-area"),
  newSession: document.querySelector("#new-session"),
  signIn: document.querySelector("#sign-in"),
  signInMessage: document.querySelector("#sign-in-message"),
  signInWidget: document.querySelector("#sign-in-widget"),
  userButton: document.querySelector("#user-button"),
};

// /clinician serves this same page. Clinician answers need a Clerk sign-in, which the
// server enforces on /ask; the patient view never loads Clerk.
const CLINICIAN = location.pathname.replace(/\/+$/, "") === "/clinician";
const ANSWER_MODE = CLINICIAN ? "clinician" : "patient";
// Clinician threads are kept apart from patient threads, stored per Clerk user, and cleared
// on sign-out. The key stays null on the clinician page until a user is known.
const CLINICIAN_HISTORY_PREFIX = "stroke-companion:clinician-thread:v1";
let historyKey = CLINICIAN ? null : "stroke-companion:thread:v1";
const HISTORY_LIMIT = 50;

let ready = false;
let signedIn = !CLINICIAN;
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

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function updateControls() {
  const busy = Boolean(activeRequest);
  ui.send.hidden = busy;
  ui.stop.hidden = !busy;
  ui.send.disabled = !ready || !signedIn || !ui.question.value.trim() || busy;
  ui.messages.setAttribute("aria-busy", String(busy));
}

function resizeQuestion() {
  ui.question.style.height = "auto";
  ui.question.style.height = `${Math.min(ui.question.scrollHeight, 200)}px`;
  updateControls();
}

function loadThread(key = historyKey) {
  if (!key) return [];
  try {
    const stored = JSON.parse(localStorage.getItem(key) || "[]");
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

function writeThread(entries, key = historyKey) {
  if (!key) return;
  while (true) {
    try {
      if (entries.length) localStorage.setItem(key, JSON.stringify(entries));
      else localStorage.removeItem(key);
      return;
    } catch (error) {
      // Drop the oldest exchanges when storage is full; give up if storage is unavailable.
      if (error?.name !== "QuotaExceededError" || entries.length <= 1) return;
      entries = entries.slice(1);
    }
  }
}

// Serialize read-modify-write cycles across tabs where the Web Locks API is available.
// Callbacks receive the key current when they were queued, so a user switch cannot redirect them.
function withHistoryLock(callback) {
  const key = historyKey;
  if (!key) return;
  if (navigator.locks?.request) navigator.locks.request(key, () => callback(key)).catch(() => {});
  else callback(key);
}

// Merge into the stored thread so exchanges saved by other tabs are kept.
function saveEntry(entry) {
  const generation = historyGeneration;
  const saved = { id: entry.id, createdAt: entry.createdAt, question: entry.question, payload: entry.payload };
  withHistoryLock((key) => {
    if (generation !== historyGeneration) return;
    const entries = loadThread(key).filter((stored) => stored.id !== saved.id);
    entries.push(saved);
    entries.sort((a, b) => a.createdAt - b.createdAt);
    writeThread(entries.slice(-HISTORY_LIMIT), key);
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

// Escape all supplied text before adding the small set of supported formatting tags.
function inlineText(text, citations, answerId) {
  return escapeHtml(text)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(\d+)\]([.,;:]?)/g, (match, id, punctuation) => {
      if (!citations.some((citation) => String(citation.id) === id)) return match;
      return `<span class="citation-reference"><button type="button" class="citation-link" data-source="${answerId}-source-${id}" aria-label="Read source ${id}" title="Read source ${id}">[${id}]</button>${punctuation}</span>`;
    });
}

function answerHtml(text, citations, answerId) {
  const blocks = [];
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
    const item = trimmed.match(/^(?:[-*]\s+|(\d+)\.\s+)(.+)$/);
    if (!trimmed || heading) {
      flushParagraph();
      flushList();
      if (heading) blocks.push(`<h2>${inline(heading[1])}</h2>`);
    } else if (item) {
      flushParagraph();
      const type = item[1] ? "ol" : "ul";
      if (listType !== type) flushList();
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
  article.querySelector(".answer-body").innerHTML = answerHtml(answer || "No answer was returned. Please try asking again.", citations, article.id);

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

async function ask(question, existingArticle = null) {
  if (activeRequest || !ready || !signedIn || !question.trim()) return;
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
    const authHeaders = CLINICIAN ? await window.appAuth.authHeaders() : {};
    if (activeRequest !== controller) return;
    response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({ question, answer_mode: ANSWER_MODE }),
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
        : response?.status === 401
          ? "Your sign-in has expired. Please sign in again, then try once more."
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
  if (!signedIn) return;
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
  if (clearStorage) withHistoryLock((key) => writeThread([], key));
  ui.messages.replaceChildren();
  ui.messages.hidden = true;
  ui.welcome.hidden = !signedIn;
  ui.question.value = "";
  ui.status.textContent = ready ? "Ready for your question" : "Temporarily unavailable";
  resizeQuestion();
}

ui.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = ui.question.value.trim();
  if (!question || activeRequest || !ready || !signedIn) return;
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
  startFresh();
  ui.question.focus();
});

// Follow changes made in other tabs; a reset there also stops this tab's pending answer.
window.addEventListener("storage", (event) => {
  // key is null when another tab called localStorage.clear().
  if ((!historyKey || event.key !== historyKey) && event.key !== null) return;
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
  source.closest("details").open = true;
  source.focus({ preventScroll: true });
  source.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

const CLINICIAN_SUGGESTIONS = [
  ["When is endovascular thrombectomy indicated?", "Thrombectomy eligibility"],
  ["What does the SPAN-100 index predict?", "SPAN-100 prognosis"],
  ["How is stroke severity assessed before hospital arrival?", "Prehospital severity scales"],
  ["What secondary prevention is recommended after a TIA?", "Secondary prevention after TIA"],
];

function applyClinicianText() {
  document.title = "Clinician view | Stroke Companion";
  document.querySelector("#welcome-eyebrow").textContent = "For clinicians";
  document.querySelector("#welcome-title").textContent = "Stroke evidence, with sources.";
  document.querySelector("#welcome-intro").textContent = "Answers use clinical language and cite the indexed literature.";
  document.querySelector("#education-note").textContent = "For clinical reference. Check answers against the cited sources and current guidelines.";
  document.querySelector("label[for='question']").textContent = "Your clinical question";
  ui.question.placeholder = "Ask a clinical question about stroke...";
  const viewSwitch = document.querySelector("#view-switch");
  viewSwitch.textContent = "Patient view";
  viewSwitch.href = "/";
  document.querySelectorAll("[data-question]").forEach((button, index) => {
    const suggestion = CLINICIAN_SUGGESTIONS[index];
    if (!suggestion) return;
    button.dataset.question = suggestion[0];
    button.querySelector("span").textContent = suggestion[1];
  });
}

// Show the sign-in form in place of the conversation, or the conversation once signed in.
function showSignedIn(value, message = "") {
  const changed = value !== signedIn;
  signedIn = value;
  ui.signIn.hidden = value;
  ui.composerArea.hidden = !value;
  ui.newSession.hidden = !value;
  if (message) ui.signInMessage.textContent = message;
  if (value && changed) renderThread();
  if (!value) {
    ui.welcome.hidden = true;
    ui.messages.hidden = true;
  }
  updateControls();
}

async function setUpClinicianSignIn() {
  applyClinicianText();
  showSignedIn(false, "Loading sign-in...");
  let state;
  try {
    state = await window.appAuth.load();
  } catch {
    showSignedIn(false, "Sign-in could not be loaded. Check your connection, then reload the page.");
    return;
  }
  if (!state.enabled) {
    historyKey = CLINICIAN_HISTORY_PREFIX;
    showSignedIn(true);
    return;
  }
  if (!state.configured) {
    showSignedIn(false, "Clinician sign-in is not set up on this server yet.");
    return;
  }
  const clerk = state.clerk;
  let signInMounted = false;
  let userButtonMounted = false;
  let currentUserId; // undefined until the first sync
  const sync = () => {
    const userId = clerk.user?.id || null;
    if (userId === currentUserId) return;
    const previousUserId = currentUserId;
    currentUserId = userId;
    // Never show one user's exchanges to another. On sign-out (here or in another tab) also
    // remove them from storage, so they are not left for whoever uses this browser next.
    if (previousUserId) startFresh(!userId);
    if (userId) {
      historyKey = `${CLINICIAN_HISTORY_PREFIX}:${userId}`;
      if (signInMounted) clerk.unmountSignIn(ui.signInWidget);
      signInMounted = false;
      if (!userButtonMounted) clerk.mountUserButton(ui.userButton);
      userButtonMounted = true;
      ui.userButton.hidden = false;
      signedIn = false; // force showSignedIn to render this user's thread
      showSignedIn(true);
    } else {
      historyKey = null;
      if (userButtonMounted) clerk.unmountUserButton(ui.userButton);
      userButtonMounted = false;
      ui.userButton.hidden = true;
      showSignedIn(false, "Clinician answers use technical language and are meant for healthcare professionals.");
      if (!signInMounted) {
        clerk.mountSignIn(ui.signInWidget, { forceRedirectUrl: location.href, signUpForceRedirectUrl: location.href });
      }
      signInMounted = true;
    }
  };
  sync();
  clerk.addListener(sync);
}

if (CLINICIAN) setUpClinicianSignIn();
else renderThread();
checkAvailability();
