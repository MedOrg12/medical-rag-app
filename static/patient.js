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
// Each entry is { question, payload }; payload stays null until an answer arrives.
let thread = [];
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
  ui.send.disabled = !ready || !ui.question.value.trim() || busy;
  ui.messages.setAttribute("aria-busy", String(busy));
}

function resizeQuestion() {
  ui.question.style.height = "auto";
  ui.question.style.height = `${Math.min(ui.question.scrollHeight, 200)}px`;
  updateControls();
}

function saveThread() {
  let entries = thread.slice(-HISTORY_LIMIT);
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

function loadThread() {
  try {
    const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(stored)) return [];
    return stored
      .filter((entry) => entry && typeof entry.question === "string" && entry.question.trim())
      .map((entry) => ({
        question: entry.question,
        payload: entry.payload && typeof entry.payload === "object" ? entry.payload : null,
      }))
      .slice(-HISTORY_LIMIT);
  } catch {
    return [];
  }
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
  if (activeRequest || !ready || !question.trim()) return;
  ui.welcome.hidden = true;
  ui.messages.hidden = false;
  if (!existingArticle) appendQuestion(question);
  const article = existingArticle || createAnswer();
  let entry = articleEntries.get(article);
  if (!entry) {
    entry = { question, payload: null };
    articleEntries.set(article, entry);
    thread.push(entry);
    saveThread();
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
    if (activeRequest !== controller) return;
    renderAnswer(article, payload);
    entry.payload = payload;
    saveThread();
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
    }
  }
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
  activeRequest?.abort();
  activeRequest = null;
  thread = [];
  saveThread();
  ui.messages.replaceChildren();
  ui.messages.hidden = true;
  ui.welcome.hidden = false;
  ui.question.value = "";
  ui.status.textContent = ready ? "Ready for your question" : "Temporarily unavailable";
  resizeQuestion();
  ui.question.focus();
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
function restoreThread() {
  thread = loadThread();
  if (!thread.length) return;
  ui.welcome.hidden = true;
  ui.messages.hidden = false;
  for (const entry of thread) {
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

restoreThread();
checkAvailability();
