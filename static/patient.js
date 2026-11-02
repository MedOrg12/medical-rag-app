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
let ready = false;
let activeRequest = null;
let answerSequence = 0;
let conversationId = crypto.randomUUID();
let savedTurns = [];
let pendingQuestion = "";

function saveConversation() {
  return BrowserState.write("patient", {
    conversationId, turns: savedTurns.slice(-50), draft: ui.question.value.slice(0, 4000), pendingQuestion,
  });
}

function restoreConversation() {
  const saved = BrowserState.read("patient");
  if (!saved || typeof saved.conversationId !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(saved.conversationId)) return;
  conversationId = saved.conversationId;
  savedTurns = (Array.isArray(saved.turns) ? saved.turns : []).filter(turn =>
    typeof turn?.question === "string" && typeof turn?.payload?.answer === "string" &&
    Array.isArray(turn.payload.citations) && turn.payload.citations.every(citation => citation && typeof citation === "object")
  ).slice(-50);
  for (const turn of savedTurns) {
    const question = document.createElement("p");
    question.className = "question-message";
    question.textContent = turn.question;
    ui.messages.append(question);
    renderAnswer(createAnswer(), turn.payload);
  }
  ui.messages.hidden = savedTurns.length === 0;
  ui.welcome.hidden = savedTurns.length > 0;
  const draft = typeof saved.draft === "string" ? saved.draft : "";
  ui.question.value = (draft || (typeof saved.pendingQuestion === "string" ? saved.pendingQuestion : "")).slice(0, 4000);
  resizeQuestion();
}

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

function createAnswer() {
  const article = document.createElement("article");
  article.className = "answer-message";
  article.id = `answer-${++answerSequence}`;
  article.innerHTML = `<div class="answer-label">${icon("heart-pulse")}<span>Stroke Companion</span></div>
    <div class="answer-body"><p class="pending"><span class="spinner" aria-hidden="true"></span>Looking through the stroke literature...</p></div>`;
  ui.messages.append(article);
  return article;
}

function citedSources(answer, citations) {
  const citedIds = new Set(Array.from(String(answer).matchAll(/\[(\d+)\]/g), match => Number(match[1])));
  return citations.filter(citation => Number.isInteger(citation.id) && citation.id > 0 && citedIds.has(citation.id));
}

function renderAnswer(article, payload) {
  const rawAnswer = String(payload.answer || "");
  const citations = citedSources(rawAnswer, payload.citations || []);
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
    note.textContent = "No sources were cited in this answer.";
    article.append(note);
  }

  const tools = document.createElement("div");
  tools.className = "answer-tools";
  if (citations.length) {
    const details = document.createElement("details");
    details.className = "sources";
    details.innerHTML = `<summary>${icon("file-text")}<span>View ${citations.length} cited source${citations.length === 1 ? "" : "s"}</span>${icon("chevron-down", "chevron")}</summary>`;
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
      const excerpt = document.createElement("blockquote");
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
  if (!existingArticle) {
    const user = document.createElement("p");
    user.className = "question-message";
    user.textContent = question;
    ui.messages.append(user);
  }
  const article = existingArticle || createAnswer();
  if (existingArticle) {
    if (ui.question.value.trim() === question) {
      ui.question.value = "";
      resizeQuestion();
    }
    article.querySelector(".answer-body").innerHTML = '<p class="pending"><span class="spinner" aria-hidden="true"></span>Looking through the stroke literature...</p>';
  }
  const controller = new AbortController();
  activeRequest = controller;
  pendingQuestion = question;
  saveConversation();
  ui.status.textContent = "Preparing your answer...";
  updateControls();
  article.scrollIntoView({ behavior: "smooth", block: "start" });
  let response;
  try {
    const payload = await streamAnswer({ question, answer_mode: "patient", conversation_id: conversationId }, controller.signal, text => {
      if (activeRequest !== controller) return;
      article.querySelector(".answer-body").textContent = text;
      article.querySelector(".answer-body").style.whiteSpace = "pre-wrap";
      ui.status.textContent = "Writing your answer...";
    });
    article.querySelector(".answer-body").style.whiteSpace = "";
    if (activeRequest !== controller) return;
    renderAnswer(article, payload);
    savedTurns.push({ question, payload });
    savedTurns = savedTurns.slice(-50);
    pendingQuestion = "";
    const persisted = saveConversation();
    ui.status.textContent = "Answer ready";
    if (!persisted) ui.status.textContent = "Answer ready. Browser history could not be saved.";
  } catch (error) {
    if (activeRequest !== controller) return;
    const body = article.querySelector(".answer-body");
    body.replaceChildren();
    const message = document.createElement("p");
    message.className = "error-message";
    message.textContent = error.name === "AbortError"
      ? "You stopped waiting for this answer."
      : response?.status === 409
        ? "The study library is not ready yet. Please try again later."
        : "We could not get an answer right now. Please try again.";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "quiet-button";
    retry.innerHTML = `${icon("rotate-ccw")}<span>Try again</span>`;
    retry.addEventListener("click", () => ask(question, article));
    body.append(message, retry);
    ui.status.textContent = error.name === "AbortError" ? "Stopped" : "Answer unavailable";
    if (!ui.question.value) {
      ui.question.value = question;
      resizeQuestion();
    }
    pendingQuestion = "";
    saveConversation();
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
ui.question.addEventListener("input", () => { resizeQuestion(); saveConversation(); });
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
  conversationId = crypto.randomUUID();
  savedTurns = [];
  pendingQuestion = "";
  BrowserState.remove("patient");
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
    saveConversation();
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
restoreConversation();
checkAvailability();
