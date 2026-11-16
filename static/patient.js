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

const LEGACY_HISTORY_KEY = "stroke-companion:thread:v1";
const HISTORY_KEY = "stroke-companion:chats:v2";
const ACTIVE_CHAT_KEY = "stroke-companion:active-chat:v2";
const HISTORY_LIMIT = 50;

let ready = false;
let activeRequest = null;
let answerSequence = 0;
let pendingSync = false;
let activeChatId = null;
let memoryChats = [];
let storageAvailable = true;
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

function cleanEntries(entries) {
  if (!Array.isArray(entries)) return [];
  return entries
    .filter((entry) => entry && typeof entry.id === "string" && typeof entry.question === "string" && entry.question.trim())
    .map((entry) => ({
      id: entry.id,
      createdAt: Number(entry.createdAt) || 0,
      question: entry.question,
      payload: entry.payload && typeof entry.payload === "object" ? entry.payload : null,
    }))
    .slice(-HISTORY_LIMIT);
}

function loadChats() {
  if (!storageAvailable) return memoryChats;
  try {
    const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(stored)) return memoryChats;
    memoryChats = stored.filter((chat) => chat && typeof chat.id === "string")
      .map((chat) => ({
        id: chat.id,
        createdAt: Number(chat.createdAt) || 0,
        updatedAt: Number(chat.updatedAt) || 0,
        entries: cleanEntries(chat.entries),
      }));
  } catch {
    // Keep the current session usable if storage is blocked or contains invalid JSON.
  }
  return memoryChats;
}

function writeChats(chats) {
  memoryChats = chats;
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(chats));
  } catch {
    storageAvailable = false;
    document.querySelector("#history-notice").textContent = "Browser storage is unavailable or full. New changes will be lost when you leave this page.";
  }
}

function withHistoryLock(callback) {
  if (navigator.locks?.request) return navigator.locks.request(HISTORY_KEY, callback).catch(() => {
    document.querySelector("#history-notice").textContent = "Could not save this change. Please try again.";
  });
  return Promise.resolve(callback());
}

function selectChatId(id) {
  activeChatId = id;
  try { sessionStorage.setItem(ACTIVE_CHAT_KEY, id || ""); } catch { /* Session remains usable. */ }
}

function loadThread() {
  return loadChats().find((chat) => chat.id === activeChatId)?.entries || [];
}

function chatTitle(chat) {
  return chat.entries[0]?.question.replace(/\s+/g, " ").trim() || "New chat";
}

function saveEntry(entry, create = false) {
  const chatId = activeChatId;
  const saved = { ...entry };
  withHistoryLock(() => {
    const chats = loadChats();
    let chat = chats.find((item) => item.id === chatId);
    // A late answer must never restore a conversation deleted in another tab.
    if (!chat && !create) return;
    if (!chat) {
      chat = { id: chatId, createdAt: saved.createdAt, updatedAt: saved.createdAt, entries: [] };
      chats.push(chat);
    }
    chat.entries = chat.entries.filter((item) => item.id !== saved.id);
    chat.entries.push(saved);
    chat.entries.sort((a, b) => a.createdAt - b.createdAt);
    chat.entries = chat.entries.slice(-HISTORY_LIMIT);
    chat.updatedAt = Date.now();
    writeChats(chats);
    renderSidebar();
  });
}

function newEntryId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function dateGroup(timestamp) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const lastWeek = new Date(today);
  lastWeek.setDate(lastWeek.getDate() - 7);
  if (timestamp >= today.getTime()) return "Today";
  if (timestamp >= yesterday.getTime()) return "Yesterday";
  if (timestamp >= lastWeek.getTime()) return "Previous 7 days";
  return "Older chats";
}

function renderSidebar() {
  const chats = [...loadChats()].filter((chat) => chat.entries.length).sort((a, b) => b.updatedAt - a.updatedAt);
  const query = document.querySelector("#history-search").value.trim().toLocaleLowerCase();
  const visible = chats.filter((chat) => !query || chat.entries.some((entry) =>
    `${entry.question} ${String(entry.payload?.answer || "")}`.toLocaleLowerCase().includes(query)));
  const history = document.querySelector("#chat-history");
  history.replaceChildren();
  document.querySelector("#conversation-title").textContent = chatTitle(chats.find((chat) => chat.id === activeChatId) || { entries: [] });
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = query ? "No chats found. Try another search." : "Your conversations will appear here. Ask a question to get started.";
    history.append(empty);
    return;
  }
  let group;
  let list;
  for (const chat of visible) {
    const label = dateGroup(chat.updatedAt);
    if (label !== group) {
      group = label;
      const heading = document.createElement("h2");
      heading.className = "history-group-title";
      heading.textContent = label;
      list = document.createElement("ul");
      list.className = "history-list";
      history.append(heading, list);
    }
    const row = document.createElement("li");
    row.className = "history-row";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "history-chat";
    open.dataset.chatId = chat.id;
    open.textContent = chatTitle(chat);
    open.title = chatTitle(chat);
    if (chat.id === activeChatId) {
      row.classList.add("active");
      open.setAttribute("aria-current", "true");
    }
    open.addEventListener("click", () => switchChat(chat.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "history-delete icon-button";
    remove.title = "Delete chat";
    remove.setAttribute("aria-label", `Delete chat: ${chatTitle(chat)}`);
    remove.innerHTML = icon("trash");
    remove.addEventListener("click", () => deleteChat(chat.id));
    row.append(open, remove);
    list.append(row);
  }
}

function stopCurrentRequest() {
  activeRequest?.abort();
  activeRequest = null;
  pendingSync = false;
}

function switchChat(id) {
  stopCurrentRequest();
  selectChatId(id);
  ui.question.value = "";
  ui.status.textContent = ready ? "Ready for your question" : "Temporarily unavailable";
  renderThread();
  renderSidebar();
  resizeQuestion();
  if (mobileSidebar.matches) setSidebar(false);
  ui.question.focus({ preventScroll: true });
}

function startFresh() {
  switchChat(null);
}

function deleteChat(id) {
  withHistoryLock(() => {
    writeChats(loadChats().filter((chat) => chat.id !== id));
    if (activeChatId === id) startFresh();
    else renderSidebar();
    document.querySelector("#history-notice").textContent = storageAvailable
      ? "Chat deleted from this browser." : "Chat removed for this session. Browser storage is unavailable.";
    document.querySelector("#new-session").focus();
  });
}

async function initializeHistory() {
  await withHistoryLock(() => {
    const chats = loadChats();
    try {
      if (localStorage.getItem(HISTORY_KEY) === null) {
        const entries = cleanEntries(JSON.parse(localStorage.getItem(LEGACY_HISTORY_KEY) || "[]"));
        if (entries.length) {
          const chat = { id: newEntryId(), createdAt: entries[0].createdAt, updatedAt: entries.at(-1).createdAt, entries };
          chats.push(chat);
          writeChats(chats);
          if (storageAvailable) localStorage.removeItem(LEGACY_HISTORY_KEY);
        }
      }
    } catch { /* Ignore malformed legacy history. */ }
    let selected;
    try { selected = sessionStorage.getItem(ACTIVE_CHAT_KEY); } catch { /* Use latest chat. */ }
    const id = selected === "" ? null : chats.some((chat) => chat.id === selected)
      ? selected : [...chats].sort((a, b) => b.updatedAt - a.updatedAt)[0]?.id || null;
    selectChatId(id);
    renderThread();
    renderSidebar();
  });
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
  if (!activeChatId) selectChatId(newEntryId());
  ui.welcome.hidden = true;
  ui.messages.hidden = false;
  if (!existingArticle) appendQuestion(question);
  const article = existingArticle || createAnswer();
  let entry = articleEntries.get(article);
  if (!entry) {
    entry = { id: newEntryId(), createdAt: Date.now(), question, payload: null };
    articleEntries.set(article, entry);
    saveEntry(entry, true);
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
    // The conversation changed or was deleted while waiting; drop the result.
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

// Other tabs update the list without changing this tab's selected conversation.
window.addEventListener("storage", (event) => {
  if (event.key !== HISTORY_KEY && event.key !== null) return;
  const chats = loadChats();
  if (activeChatId && !chats.some((chat) => chat.id === activeChatId)) startFresh();
  else if (activeRequest) pendingSync = true;
  else queueRenderThread();
  renderSidebar();
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

const mobileSidebar = window.matchMedia("(max-width: 800px)");
const sidebar = document.querySelector("#chat-sidebar");
const workspace = document.querySelector("#workspace");
const sidebarToggle = document.querySelector("#toggle-sidebar");
let sidebarOpen = !mobileSidebar.matches;

function setSidebar(open) {
  sidebarOpen = open;
  document.body.classList.toggle("sidebar-open", open);
  document.body.classList.toggle("sidebar-collapsed", !open);
  sidebar.inert = !open;
  workspace.inert = open && mobileSidebar.matches;
  document.querySelector("#sidebar-backdrop").hidden = !(open && mobileSidebar.matches);
  sidebarToggle.setAttribute("aria-expanded", String(open));
  sidebarToggle.setAttribute("aria-label", open ? "Close sidebar" : "Open sidebar");
  sidebarToggle.title = open ? "Close sidebar" : "Open sidebar";
  if (open && mobileSidebar.matches) document.querySelector("#close-sidebar").focus();
}

sidebarToggle.addEventListener("click", () => setSidebar(!sidebarOpen));
document.querySelector("#close-sidebar").addEventListener("click", () => {
  setSidebar(false);
  sidebarToggle.focus();
});
document.querySelector("#sidebar-backdrop").addEventListener("click", () => {
  setSidebar(false);
  sidebarToggle.focus();
});
document.querySelector("#history-search").addEventListener("input", renderSidebar);
mobileSidebar.addEventListener("change", () => setSidebar(!mobileSidebar.matches));
document.addEventListener("keydown", (event) => {
  if (!sidebarOpen || !mobileSidebar.matches) return;
  if (event.key === "Escape") {
    setSidebar(false);
    sidebarToggle.focus();
  } else if (event.key === "Tab") {
    const buttons = [...sidebar.querySelectorAll("a, button, input")];
    const first = buttons[0];
    const last = buttons.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }
});
setSidebar(sidebarOpen);
initializeHistory().then(checkAvailability);
