"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  view: "playground", health: null, answerMode: "patient", sources: null, sourcePage: 0,
  sourceLoading: false, questions: null, selected: new Set(), questionLoading: false,
  query: null, queryRequest: null, queryTimer: null, eval: null, evalBusy: false,
  ingestBusy: false, ingestTimer: null, ingestChecking: false,
  libraryRevision: null, editorSource: null, editorRevision: null, curationSaving: false,
};
const pageSize = 50;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const number = (value) => new Intl.NumberFormat().format(Number(value || 0));
const percent = (value) => `${Math.round(Number(value || 0) * 100)}%`;
const seconds = (value) => `${Number(value || 0).toFixed(1)}s`;
const icon = (name) => `<svg aria-hidden="true"><use href="/static/icons.svg#${name}"></use></svg>`;

async function request(path, body, signal) {
  // Every workbench endpoint needs an administrator's Clerk session token.
  const authHeaders = await window.appAuth.authHeaders();
  const response = await fetch(path, body === undefined ? { signal, headers: authHeaders } : {
    method: "POST", headers: { "Content-Type": "application/json", ...authHeaders }, body: JSON.stringify(body), signal,
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload));
    error.status = response.status;
    throw error;
  }
  return payload;
}

function notice(selector, text, tone = "") {
  const element = $(selector);
  element.hidden = !text;
  element.className = `notice ${tone}`;
  element.textContent = text;
}

function announce(text) { $("#action-status").textContent = text; }

function showView() {
  const requested = location.hash.slice(1);
  state.view = ["playground", "documents", "evaluations", "system"].includes(requested) ? requested : "playground";
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== `view-${state.view}`; });
  document.querySelectorAll("[data-view]").forEach((link) => {
    if (link.dataset.view === state.view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("#view-name").textContent = state.view[0].toUpperCase() + state.view.slice(1);
  if (state.view === "documents") {
    if (state.sources === null) loadSources();
    checkIngestion();
  }
  if (state.view === "evaluations" && state.questions === null) loadQuestions();
}

async function loadHealth() {
  try {
    state.health = await request("/health");
    notice("#connection-error", "");
    renderHealth();
    $("#last-refreshed").textContent = `Checked ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    state.health = null;
    $("#index-status").textContent = "Server unavailable";
    $("#index-status").className = "badge error";
    notice("#connection-error", `Could not load server configuration: ${error.message}`, "error");
  }
  queryControls();
  evaluationControls();
}

function configGroup(title, entries) {
  return `<section class="system-group"><h2>${esc(title)}</h2><dl>${entries.map(([label, value]) => `<div class="config-row"><dt>${esc(label)}</dt><dd>${esc(value ?? "Not configured")}</dd></div>`).join("")}</dl></section>`;
}

function renderHealth() {
  const h = state.health;
  $("#index-status").className = `badge ${h.vector_store_error ? "error" : h.index_exists ? "ok" : "warning"}`;
  $("#index-status").textContent = h.vector_store_error ? "Store unavailable" : h.index_exists ? "Index ready" : "No index";
  $("#source-path").placeholder = h.corpus_dir || "Default corpus directory";
  $("#query-models").innerHTML = `<span>Generation <strong>${esc(h.generation_model)}</strong></span><span>Embeddings <strong>${esc(h.active_embedding_model)}</strong></span>`;
  const warnings = [];
  if (h.vector_store_error) warnings.push(h.vector_store_error);
  else if (!h.index_exists) warnings.push("No index is available. Index documents before running queries or evaluations.");
  if (h.embedding_model_error) warnings.push(h.embedding_model_error);
  if (h.fallback_embedding) warnings.push("Hash fallback embeddings are active.");
  if (h.generation_backend === "extractive") warnings.push("Extractive mode is active; answers will contain source excerpts.");
  if (h.generation_backend === "api" && !h.api_key_configured) warnings.push("The generation API key is missing.");
  if (h.generation_backend === "ollama" && !h.ollama_available) warnings.push("No Ollama models were detected.");
  notice("#query-warning", warnings.length ? warnings.join(" ") : "", "warning");
  $("#system-alerts").innerHTML = warnings.map((warning) => `<div class="notice warning">${esc(warning)}</div>`).join("");
  let html = configGroup("Generation", [["Backend", h.generation_backend], ["Model", h.generation_model], ["Request timeout", `${h.request_timeout_seconds}s`]]);
  if (h.generation_backend === "api" || h.embedding_backend === "api") {
    html += configGroup("API provider", [["Base URL", h.api_base_url], ["API key", h.api_key_configured ? "Configured (not a connectivity test)" : "Missing"], ["Generation model", h.api_generation_model], ["Embedding model", h.api_embedding_model], ["Output token limit", h.api_max_output_tokens || "Provider default"], ["Reasoning effort", h.api_reasoning_effort || "Automatic"], ["Retries", h.api_max_retries]]);
  }
  html += configGroup("Retrieval", [["Configured backend", h.embedding_backend], ["Active embedding model", h.active_embedding_model], ["Fallback embeddings", h.fallback_embedding ? "Active" : "Inactive"]]);
  const storage = [["Backend", h.vector_store_backend || "json"], ["Corpus directory", h.corpus_dir]];
  if (h.vector_store_backend === "qdrant") storage.push(["Qdrant URL", h.qdrant_url], ["Collection", h.qdrant_collection]);
  else storage.push(["Index path", h.index_path]);
  storage.push(["Index", h.vector_store_error ? "Unavailable" : h.index_exists ? "Available" : "Missing"]);
  html += configGroup("Storage", storage);
  if (h.generation_backend === "ollama" || ["auto", "ollama"].includes(h.embedding_backend)) {
    html += configGroup("Ollama", [["Installed models", (h.ollama_models || []).join(", ") || "None detected"], ["Embedding model", h.ollama_embedding_model], ["Embedding model installed", h.ollama_embedding_model_available ? "Yes" : "No"]]);
  }
  $("#system-details").innerHTML = html;
  $("#health-json").textContent = JSON.stringify(h, null, 2);
}

function queryControls() {
  const busy = Boolean(state.queryRequest);
  $("#ask-button").disabled = busy || !$("#question").value.trim() || state.health?.index_exists === false;
  $("#stop-query").hidden = !busy;
  $("#top-k").disabled = busy;
  $("#example-question").disabled = busy;
  document.querySelectorAll("[data-mode]").forEach((button) => { button.disabled = busy; });
  document.querySelectorAll(".library-filters input, .library-filters select").forEach((control) => {control.disabled = busy;});
  $("#scope-inactive").disabled = busy || state.answerMode !== "clinician";
}

function clearQuery() {
  state.queryRequest?.abort();
  state.queryRequest = null;
  clearInterval(state.queryTimer);
  state.query = null;
  $("#question").value = "";
  $("#example-question").value = "";
  document.querySelectorAll(".library-filters select").forEach((control) => {control.value = "";});
  $("#scope-reviewed").checked = $("#scope-inactive").checked = false;
  $("#query-result").hidden = true;
  $("#query-empty").hidden = false;
  $("#query-status").textContent = "No query run yet";
  notice("#query-error", "");
  queryControls();
  $("#question").focus();
}

async function runQuery(event) {
  event.preventDefault();
  if (state.queryRequest || !$("#ask-form").reportValidity()) return;
  const inputs = { question: $("#question").value.trim(), answer_mode: state.answerMode, top_k: Number($("#top-k").value) };
  inputs.library_filters = {
    document_types: $("#scope-type").value ? [$("#scope-type").value] : [],
    populations: $("#scope-population").value ? [$("#scope-population").value] : [],
    topics: $("#scope-topic").value ? [$("#scope-topic").value] : [],
    jurisdiction: $("#scope-jurisdiction").value || null,
    reviewed_only: $("#scope-reviewed").checked,
    include_inactive: state.answerMode === "clinician" && $("#scope-inactive").checked,
  };
  if (!inputs.question) return;
  const controller = new AbortController();
  state.queryRequest = controller;
  state.query = null;
  $("#query-result").hidden = true;
  $("#query-empty").hidden = true;
  notice("#query-error", "");
  const started = performance.now();
  const progress = () => { $("#query-status").textContent = `Running query · ${seconds((performance.now() - started) / 1000)}`; };
  progress();
  state.queryTimer = setInterval(progress, 500);
  queryControls();
  try {
    const payload = await request("/ask", inputs, controller.signal);
    if (state.queryRequest !== controller) return;
    const latency = (performance.now() - started) / 1000;
    state.query = { request: inputs, latency_seconds: latency, response: payload };
    renderQuery();
    $("#query-status").textContent = `Completed in ${seconds(latency)}`;
  } catch (error) {
    if (state.queryRequest !== controller) return;
    $("#query-status").textContent = error.name === "AbortError" ? "Stopped waiting" : "Query failed";
    notice("#query-error", error.name === "AbortError" ? "Stopped waiting for this response." : error.message, error.name === "AbortError" ? "" : "error");
  } finally {
    if (state.queryRequest === controller) {
      clearInterval(state.queryTimer);
      state.queryRequest = null;
      queryControls();
    }
  }
}

function evidenceHtml(citations, prefix) {
  return EvidenceUI.sources(citations, prefix, true) || '<p class="muted">No sources cited in this answer.</p>';
}

function renderQuery() {
  const { response: payload, request: inputs, latency_seconds: latency } = state.query;
  const citations = payload.citations || [];
  const answer = String(payload.answer || "No answer returned.");
  const fallback = answer.includes("Generation backend was unavailable");
  $("#query-metadata").innerHTML = `<span class="run-question"><strong>Question:</strong> ${esc(inputs.question)}</span><span><strong>${esc(inputs.answer_mode)}</strong> mode</span><span><strong>${inputs.top_k}</strong> requested passages</span><span>${esc(payload.retrieval_mode || "vector")} retrieval</span><span>${esc(payload.retrieval_model)}</span><span>${esc(payload.generation_model)}</span>${fallback ? '<span class="badge warning">Generation fallback</span>' : ""}<span>${seconds(latency)}</span>`;
  if (payload.timings) {
    const stages = [["Index load", "index_load_seconds"], ["Retrieval", "retrieval_seconds"], ["Reranking", "reranking_seconds"], ["Generation", "generation_seconds"]];
    $("#query-metadata").innerHTML += `<span class="run-question muted">${stages.map(([label, key]) => `${label} ${seconds(payload.timings[key])}`).join(" · ")}</span>`;
  }
  $("#answer").innerHTML = EvidenceUI.answer(answer, citations, "query-evidence");
  $("#query-conflicts").innerHTML = EvidenceUI.conflicts(payload.evidence_conflicts || [], "query-evidence");
  if (payload.library_scope) {
    const scope = payload.library_scope;
    const labels = [...(scope.document_types || []).map((type) => type.replaceAll("_", " ")), ...(scope.populations || []), ...(scope.topics || []), scope.jurisdiction].filter(Boolean);
    $("#query-metadata").innerHTML += `<span class="run-question">${scope.include_inactive ? "Historical sources included" : "Superseded and withdrawn sources excluded"}${scope.reviewed_only ? " · Reviewed metadata only" : ""}${labels.length ? ` · ${labels.map(esc).join(" · ")}` : ""}</span>`;
  }
  $("#evidence-count").textContent = `${citations.length} cited`;
  $("#evidence-warnings").innerHTML = EvidenceUI.warnings(payload.citation_validation)
    + '<p class="evidence-review-note">Claim support requires review against the original sources.</p>';
  $("#evidence-list").innerHTML = evidenceHtml(citations, "query-evidence");
  const otherEvidence = payload.retrieved_evidence || [];
  $("#other-evidence").hidden = !otherEvidence.length;
  $("#other-evidence").open = false;
  $("#other-evidence-count").textContent = `(${otherEvidence.length})`;
  $("#other-evidence-list").innerHTML = evidenceHtml(otherEvidence, "query-evidence");
  $("#query-json").textContent = JSON.stringify(state.query, null, 2);
  $("#query-result").hidden = false;
}

async function loadSources() {
  if (state.sourceLoading) return;
  state.sourceLoading = true;
  notice("#source-error", "");
  try {
    const library = await request("/library");
    state.sources = library.documents;
    state.libraryRevision = library.revision;
    fillScopeOptions(library.facets);
    $("#source-count").textContent = number(state.sources.length);
    $("#chunk-count").textContent = number(state.sources.reduce((sum, source) => sum + Number(source.chunks || 0), 0));
    $("#page-count").textContent = state.sources.every((source) => Array.isArray(source.pages))
      ? number(state.sources.reduce((sum, source) => sum + source.pages.length, 0))
      : "-";
    $("#curation-summary").textContent = `${number(state.sources.filter((source) => source.metadata.status === "unreviewed").length)} unreviewed`;
  } catch (error) {
    state.sources = [];
    ["#source-count", "#chunk-count", "#page-count"].forEach((selector) => { $(selector).textContent = "-"; });
    notice("#source-error", error.status === 409 ? "No indexed library yet. Index documents to get started." : error.message, error.status === 409 ? "" : "error");
  } finally {
    state.sourceLoading = false;
    renderSources();
  }
}

function renderSources() {
  const query = $("#source-search").value.trim().toLowerCase();
  const filtered = (state.sources || []).filter((source) => {
    const m = source.metadata || {};
    return `${source.source_id} ${source.title} ${(m.populations || []).join(" ")} ${(m.topics || []).join(" ")} ${m.jurisdiction || ""}`.toLowerCase().includes(query)
      && (!$("#source-type-filter").value || m.document_type === $("#source-type-filter").value)
      && (!$("#source-status-filter").value || m.status === $("#source-status-filter").value);
  });
  state.sourcePage = Math.min(state.sourcePage, Math.max(0, Math.ceil(filtered.length / pageSize) - 1));
  const start = state.sourcePage * pageSize;
  const slice = filtered.slice(start, start + pageSize);
  $("#sources").innerHTML = slice.map((source) => {
    const m = source.metadata || {};
    const tone = m.status === "current" ? "ok" : m.status === "withdrawn" ? "error" : "warning";
    return `<tr><td><strong>${esc(source.title || source.source_id)}</strong><span class="source-path">${esc(source.source_id)}</span>${m.publication_date || m.publication_year ? `<span class="source-path">${esc(m.publication_date || m.publication_year)}${m.document_version ? ` · ${esc(m.document_version)}` : ""}</span>` : ""}</td><td>${esc((m.document_type || "unclassified").replaceAll("_", " "))}<span class="source-path">${esc((m.populations || []).join(", ") || "Population not recorded")}</span></td><td><span class="badge ${tone}">${esc(m.status || "unreviewed")}</span></td><td>${Array.isArray(source.pages) ? number(source.pages.length) : "-"} / ${number(source.chunks)}</td><td><button class="icon-button" type="button" data-curate="${esc(source.source_id)}" title="Edit document metadata" aria-label="Edit metadata for ${esc(source.source_id)}">${icon("settings-2")}</button></td></tr>`;
  }).join("") || '<tr><td colspan="5" class="table-empty">No matching documents</td></tr>';
  $("#source-range").textContent = filtered.length ? `${number(start + 1)}-${number(Math.min(start + pageSize, filtered.length))} of ${number(filtered.length)} documents` : "0 documents";
  $("#source-prev").disabled = state.sourcePage === 0;
  $("#source-next").disabled = start + pageSize >= filtered.length;
}

function fillScopeOptions(facets = {}) {
  for (const [selector, values, label] of [["#scope-population", facets.populations || [], "All populations"], ["#scope-topic", facets.topics || [], "All topics"], ["#scope-jurisdiction", facets.jurisdictions || [], "All jurisdictions"]]) {
    const select = $(selector);
    const previous = select.value;
    const options = [...new Set([...values, ...(previous ? [previous] : [])])].sort();
    select.innerHTML = `<option value="">${label}</option>` + options.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
    select.value = previous;
  }
  $("#jurisdiction-options").innerHTML = (facets.jurisdictions || []).map((value) => `<option value="${esc(value)}"></option>`).join("");
}

function counterpartOptions(selected = "") {
  return '<option value="">Choose an indexed document</option>' + (state.sources || []).filter((source) => source.source_id !== state.editorSource).map((source) => `<option value="${esc(source.source_id)}"${source.source_id === selected ? " selected" : ""}>${esc(source.title || source.source_id)} (${esc(source.source_id)})</option>`).join("");
}

function addConflict(note = {}) {
  const row = document.createElement("fieldset");
  row.className = "conflict-editor";
  row.innerHTML = `<legend class="sr-only">Curator-recorded disagreement</legend><div class="section-heading compact"><span class="muted">Curator-recorded disagreement</span><button class="icon-button remove-conflict" type="button" title="Remove disagreement" aria-label="Remove disagreement">${icon("x")}</button></div><div class="form-grid">
    <label>Other document<select data-conflict="with_source" required>${counterpartOptions(note.with_source)}</select></label>
    <label>Topic<input data-conflict="topic" maxlength="200" value="${esc(note.topic || "")}" required /></label>
    <label>This document's position<textarea data-conflict="source_position" rows="2" maxlength="2000" required>${esc(note.source_position || "")}</textarea></label>
    <label>Other document's position<textarea data-conflict="other_position" rows="2" maxlength="2000" required>${esc(note.other_position || "")}</textarea></label>
    <label>This document's PDF page<input data-conflict="source_page" type="number" min="1" value="${esc(note.source_page || "")}" /></label>
    <label>Other document's PDF page<input data-conflict="other_page" type="number" min="1" value="${esc(note.other_page || "")}" /></label>
    <label class="span-all">Population, setting, or evidence context<textarea data-conflict="context" rows="2" maxlength="2000" required>${esc(note.context || "")}</textarea></label>
    </div>`;
  $("#curation-conflicts").append(row);
}

function openCuration(sourceId) {
  const source = (state.sources || []).find((item) => item.source_id === sourceId);
  if (!source) return;
  state.editorSource = sourceId;
  state.editorRevision = state.libraryRevision;
  const m = source.metadata || {};
  $("#curation-source").textContent = sourceId;
  const fields = { title: "title", publisher: "publisher", type: "document_type", date: "publication_date", year: "publication_year", version: "document_version", jurisdiction: "jurisdiction", status: "status", reviewer: "reviewed_by", notes: "review_notes" };
  for (const [id, key] of Object.entries(fields)) $("#curate-" + id).value = m[key] ?? (id === "title" ? source.title || "" : id === "status" ? "unreviewed" : id === "type" ? "unclassified" : "");
  $("#curate-populations").value = (m.populations || []).join(", ");
  $("#curate-topics").value = (m.topics || []).join(", ");
  $("#curate-replacement").innerHTML = '<option value="">Replacement not recorded</option>' + counterpartOptions(m.superseded_by).replace('<option value="">Choose an indexed document</option>', "");
  $("#curate-replacement").value = m.superseded_by || "";
  $("#curation-conflicts").replaceChildren();
  (m.conflicts || []).forEach(addConflict);
  notice("#curation-error", "");
  $("#reload-curation").hidden = true;
  updateCurationStatus();
  if (!$("#curation-dialog").open) $("#curation-dialog").showModal();
}

function updateCurationStatus() {
  const status = $("#curate-status").value;
  $("#replacement-field").hidden = status !== "superseded";
  $("#curate-notes").required = ["superseded", "withdrawn"].includes(status);
}

async function saveCuration(event) {
  event.preventDefault();
  if (state.curationSaving || !$("#curation-form").reportValidity()) return;
  state.curationSaving = true;
  $("#save-curation").disabled = true;
  $("#save-curation").textContent = "Saving...";
  notice("#curation-error", "");
  const text = (id) => $("#curate-" + id).value.trim() || null;
  const tags = (id) => (text(id) || "").split(",").map((value) => value.trim()).filter(Boolean);
  const conflicts = [...document.querySelectorAll(".conflict-editor")].map((row) => Object.fromEntries([...row.querySelectorAll("[data-conflict]")].map((field) => [field.dataset.conflict, field.type === "number" ? (field.value ? Number(field.value) : null) : field.value.trim()])));
  const metadata = {title: text("title"), publisher: text("publisher"), document_type: text("type"), publication_date: text("date"), publication_year: text("year") ? Number(text("year")) : null, document_version: text("version"), jurisdiction: text("jurisdiction"), populations: tags("populations"), topics: tags("topics"), status: text("status"), reviewed_by: text("reviewer"), review_notes: text("notes"), superseded_by: text("status") === "superseded" ? text("replacement") : null, conflicts};
  try {
    await request("/library/documents", {source_id: state.editorSource, revision: state.editorRevision, metadata});
    $("#curation-dialog").close();
    await loadSources();
    announce("Document metadata saved");
  } catch (error) {
    notice("#curation-error", error.message, "error");
    $("#reload-curation").hidden = error.status !== 409;
  } finally {
    state.curationSaving = false;
    $("#save-curation").disabled = false;
    $("#save-curation").textContent = "Save metadata";
  }
}

function ingestControls() {
  $("#ingest-form").querySelectorAll("input, select, button").forEach((control) => { control.disabled = state.ingestBusy; });
}

function showIngestPanel(open) {
  $("#ingest-panel").hidden = !open;
  $("#open-ingest").setAttribute("aria-expanded", String(open));
  if (open) $("#source-path").focus();
}

async function startIngestion(event) {
  event.preventDefault();
  if (state.ingestBusy || !$("#ingest-form").reportValidity()) return;
  const mode = $("#ingest-mode").value;
  const body = { source_path: $("#source-path").value.trim() || null, pdf_workers: Number($("#pdf-workers").value), background: $("#background-ingest").checked, ocr_scanned: $("#ocr-scanned").checked, resume: mode !== "force", force: mode === "force", failed_only: mode === "failed" };
  state.ingestBusy = true;
  ingestControls();
  notice("#ingest-result", "Starting indexing...");
  $("#ingest-report").hidden = true;
  try {
    const payload = await request("/ingest", body);
    if (payload.accepted) {
      notice("#ingest-result", "Indexing is running in the background.");
      checkIngestion();
    } else {
      state.ingestBusy = false;
      renderIngestReport(payload);
      loadSources();
      loadHealth();
    }
  } catch (error) {
    state.ingestBusy = false;
    notice("#ingest-result", `Indexing could not start: ${error.message}`, "error");
    if (error.status === 409) checkIngestion();
  } finally { ingestControls(); }
}

function renderIngestReport(report) {
  notice("#ingest-result", report.files_failed ? `Indexing completed with ${number(report.files_failed)} failed files.` : "Indexing completed.", report.files_failed ? "warning" : "");
  const items = [["Documents", report.documents], ["Chunks", report.chunks], ["Changed", report.files_changed], ["Cached", report.files_from_cache], ["Failed", report.files_failed], ["Duplicates", report.duplicate_files]];
  $("#ingest-report").innerHTML = items.map(([label, value]) => `<span>${esc(label)} <strong>${number(value)}</strong></span>`).join("") + (report.timings?.total_seconds != null ? `<span>Duration <strong>${seconds(report.timings.total_seconds)}</strong></span>` : "");
  $("#ingest-report").hidden = false;
}

async function checkIngestion() {
  if (state.ingestChecking) return;
  clearTimeout(state.ingestTimer);
  state.ingestChecking = true;
  const wasBusy = state.ingestBusy;
  try {
    const status = await request("/ingest/status");
    state.ingestBusy = Boolean(status.running);
    if (status.running) {
      const time = status.started_at ? ` Started ${new Date(status.started_at * 1000).toLocaleTimeString()}.` : "";
      notice("#ingest-result", `Indexing is running.${time}`);
    } else if (status.last_error) {
      notice("#ingest-result", `Indexing failed: ${status.last_error}`, "error");
    } else if (status.last_report) {
      renderIngestReport(status.last_report);
    }
    if (wasBusy && !status.running) { loadSources(); loadHealth(); }
  } catch (error) {
    notice("#ingest-result", `Could not check indexing status: ${error.message}`, "error");
  } finally {
    state.ingestChecking = false;
    ingestControls();
    if (state.ingestBusy) state.ingestTimer = setTimeout(checkIngestion, 1500);
  }
}

async function loadQuestions() {
  if (state.questionLoading || state.evalBusy) return;
  state.questionLoading = true;
  evaluationControls();
  try {
    const payload = await request("/eval/questions");
    const firstLoad = state.questions === null;
    state.questions = payload.questions || [];
    if (firstLoad) state.selected = new Set(state.questions.map((q) => q.id));
    else state.selected = new Set(state.questions.filter((q) => state.selected.has(q.id)).map((q) => q.id));
    $("#eval-question-list").innerHTML = state.questions.map((q, index) => `<div class="eval-question"><input id="eval-question-${index}" type="checkbox" data-question-id="${esc(q.id)}" ${state.selected.has(q.id) ? "checked" : ""} /><div><label for="eval-question-${index}">${esc(q.question)}${q.should_refuse ? '<span class="badge">Refusal check</span>' : ""}</label><details class="expectations"><summary>Expected evidence</summary><p>Sources: ${esc((q.expected_source_hints || []).join(", ") || "None")}</p><p>Answer terms: ${esc((q.expected_answer_terms || []).join(", ") || "None")}</p></details></div></div>`).join("") || '<p class="muted">No questions in the suite.</p>';
    notice("#eval-error", "");
  } catch (error) {
    notice("#eval-error", `Could not load question set: ${error.message}`, "error");
    $("#eval-question-list").textContent = "Question set unavailable.";
  } finally {
    state.questionLoading = false;
    evaluationControls();
  }
}

function evaluationControls() {
  const count = state.selected.size;
  $("#eval-run-label").textContent = state.evalBusy ? "Running..." : `Run ${count || "selected"}${count ? ` question${count === 1 ? "" : "s"}` : ""}`;
  $("#selected-count").textContent = `${count} of ${(state.questions || []).length} selected`;
  $("#eval-run-button").disabled = state.evalBusy || state.questionLoading || !count || state.health?.index_exists === false;
  $("#select-all").checked = count > 0 && count === (state.questions || []).length;
  $("#select-all").indeterminate = count > 0 && count < (state.questions || []).length;
  document.querySelectorAll('#eval-question-list input, #select-all, #eval-answer-mode, #eval-top-k, #eval-include-answers, #reload-eval-questions').forEach((input) => { input.disabled = state.evalBusy || state.questionLoading; });
}

async function runEvaluation() {
  if (state.evalBusy || !state.selected.size || !$("#eval-top-k").reportValidity()) return;
  state.evalBusy = true;
  evaluationControls();
  notice("#eval-error", "");
  $("#eval-output").hidden = true;
  const body = { answer_mode: $("#eval-answer-mode").value, top_k: Number($("#eval-top-k").value), question_ids: [...state.selected], include_answers: $("#eval-include-answers").checked };
  const started = performance.now();
  const progress = () => { $("#eval-status").textContent = `Running ${body.question_ids.length} questions · ${seconds((performance.now() - started) / 1000)}`; };
  progress();
  const timer = setInterval(progress, 1000);
  try {
    state.eval = await request("/eval/run", body);
    renderEvaluation();
    $("#question-selection").open = false;
    const summary = state.eval.summary;
    $("#eval-status").textContent = `Completed · ${summary.passed_questions}/${summary.total_questions} passed · ${seconds(summary.duration_seconds)}`;
  } catch (error) {
    $("#eval-status").textContent = "Evaluation failed";
    notice("#eval-error", error.message, "error");
  } finally {
    clearInterval(timer);
    state.evalBusy = false;
    evaluationControls();
  }
}

function renderEvaluation() {
  const s = state.eval.summary;
  const stat = (label, value) => `<div><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
  $("#eval-summary").innerHTML = [stat("Passed", `${s.passed_questions}/${s.total_questions}`), stat("Retrieval hit rate", s.in_scope_questions ? percent(s.retrieval_hit_rate) : "N/A"), stat("Citation term coverage", s.in_scope_questions ? percent(s.average_citation_term_coverage) : "N/A"), stat("Answer term coverage", s.in_scope_questions ? percent(s.average_answer_term_coverage) : "N/A"), stat("Refusal accuracy", s.negative_controls ? percent(s.refusal_accuracy) : "N/A")].join("");
  $("#eval-run-metadata").textContent = `${state.eval.answer_mode || "Default"} mode · ${state.eval.top_k ?? "Default"} passages · ${number(s.failed_questions)} failed · ${number(s.error_questions)} error${s.error_questions === 1 ? "" : "s"} · Suite v${state.eval.version}`;
  const filter = $("#eval-filter").value;
  const results = state.eval.results.filter((r) => filter === "all" || r.status === filter);
  $("#eval-results").innerHTML = results.map((r, index) => {
    const tone = ["pass", "fail", "error"].includes(r.status) ? r.status : "";
    return `<details class="eval-result"><summary><span class="badge ${tone}">${esc(r.status)}</span><span class="result-title">${esc(r.question)}<span class="result-subtitle">${esc(r.question_id)} · ${seconds(r.latency_seconds)}${r.should_refuse ? " · Refusal check" : ""}</span></span>${icon("chevron-down")}</summary><div class="eval-detail"><div class="metrics"><span>Retrieval: <strong>${r.retrieval_hit ? "Hit" : "Miss"}</strong></span><span>Citation terms: <strong>${percent(r.citation_term_coverage)}</strong></span><span>Answer terms: <strong>${percent(r.answer_term_coverage)}</strong></span><span>Refused: <strong>${r.refused ? "Yes" : "No"}</strong></span></div>${r.error ? `<div class="notice error">${esc(r.error)}</div>` : ""}<p><strong>Missing answer terms:</strong> ${esc((r.answer_terms_missing || []).join(", ") || "None")}</p><p><strong>Matched source hints:</strong> ${esc((r.source_hints_found || []).join(", ") || "None")}</p><div class="eval-answer">${esc(r.answer || r.answer_snippet || "No answer returned.")}</div><h3>Citations</h3>${evidenceHtml(r.citations || [], `eval-${index}-evidence`)}</div></details>`;
  }).join("") || '<div class="empty-state"><p>No matching results</p></div>';
  $("#eval-output").hidden = false;
}

function download(payload, filename) {
  if (!payload) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("#ask-form").addEventListener("submit", runQuery);
$("#question").addEventListener("input", queryControls);
$("#question").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.isComposing) { event.preventDefault(); if (!$("#ask-button").disabled) $("#ask-form").requestSubmit(); }
});
$("#stop-query").addEventListener("click", () => state.queryRequest?.abort());
$("#clear-query").addEventListener("click", clearQuery);
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.answerMode = button.dataset.mode;
  if (state.answerMode !== "clinician") $("#scope-inactive").checked = false;
  queryControls();
  document.querySelectorAll("[data-mode]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
}));
$("#example-question").addEventListener("change", () => { if ($("#example-question").value) { $("#question").value = $("#example-question").value; $("#question").focus(); queryControls(); } });
$("#answer").addEventListener("click", (event) => { const button = event.target.closest("[data-source]"); if (button) { const source = document.getElementById(button.dataset.source); source?.focus(); source?.scrollIntoView({ behavior: "smooth", block: "nearest" }); } });
$("#query-conflicts").addEventListener("click", (event) => { const button = event.target.closest("[data-source]"); if (button) { const source = document.getElementById(button.dataset.source); if (source?.closest("details")) source.closest("details").open = true; source?.focus(); source?.scrollIntoView({ behavior: "smooth", block: "nearest" }); } });
$("#copy-answer").addEventListener("click", async () => { try { await navigator.clipboard.writeText(state.query.response.answer); announce("Answer copied"); } catch { announce("Could not copy answer"); } });
$("#download-query").addEventListener("click", () => download(state.query, "rag-query.json"));
$("#open-ingest").addEventListener("click", () => showIngestPanel($("#ingest-panel").hidden));
$("#close-ingest").addEventListener("click", () => showIngestPanel(false));
$("#ingest-form").addEventListener("submit", startIngestion);
$("#source-search").addEventListener("input", () => { state.sourcePage = 0; renderSources(); });
document.querySelector(".library-filters").addEventListener("toggle", (event) => {if (event.target.open && state.sources === null) loadSources();});
["#source-type-filter", "#source-status-filter"].forEach((selector) => $(selector).addEventListener("change", () => {state.sourcePage = 0; renderSources();}));
$("#sources").addEventListener("click", (event) => { const button = event.target.closest("[data-curate]"); if (button) openCuration(button.dataset.curate); });
$("#curation-form").addEventListener("submit", saveCuration);
$("#curate-status").addEventListener("change", updateCurationStatus);
$("#curate-date").addEventListener("change", () => { if ($("#curate-date").value) $("#curate-year").value = $("#curate-date").value.slice(0, 4); });
$("#add-conflict").addEventListener("click", () => addConflict());
$("#curation-conflicts").addEventListener("click", (event) => { const button = event.target.closest(".remove-conflict"); if (button) button.closest("fieldset").remove(); });
["#close-curation", "#cancel-curation"].forEach((selector) => $(selector).addEventListener("click", () => { if (!state.curationSaving) $("#curation-dialog").close(); }));
$("#curation-dialog").addEventListener("cancel", (event) => { if (state.curationSaving) event.preventDefault(); });
$("#reload-curation").addEventListener("click", async () => { await loadSources(); openCuration(state.editorSource); });
$("#source-prev").addEventListener("click", () => { state.sourcePage--; renderSources(); });
$("#source-next").addEventListener("click", () => { state.sourcePage++; renderSources(); });
$("#eval-question-list").addEventListener("change", (event) => { const id = event.target.dataset.questionId; if (id) { if (event.target.checked) state.selected.add(id); else state.selected.delete(id); evaluationControls(); } });
$("#select-all").addEventListener("change", () => { state.selected = new Set($("#select-all").checked ? (state.questions || []).map((q) => q.id) : []); $("#eval-question-list").querySelectorAll("input").forEach((input) => { input.checked = state.selected.has(input.dataset.questionId); }); evaluationControls(); });
$("#reload-eval-questions").addEventListener("click", loadQuestions);
$("#eval-run-button").addEventListener("click", runEvaluation);
$("#eval-filter").addEventListener("change", () => { if (state.eval) renderEvaluation(); });
$("#download-eval").addEventListener("click", () => download(state.eval, "rag-evaluation.json"));
$("#refresh-button").addEventListener("click", async () => {
  $("#refresh-button").disabled = true;
  const operations = [loadHealth()];
  if (state.view === "documents") operations.push(loadSources(), checkIngestion());
  if (state.view === "evaluations") operations.push(loadQuestions());
  await Promise.allSettled(operations);
  $("#refresh-button").disabled = false;
});
window.addEventListener("pagehide", () => { clearTimeout(state.ingestTimer); clearInterval(state.queryTimer); });

function gate(message, { signOut = false } = {}) {
  $("#auth-gate").hidden = false;
  $("#auth-gate-message").textContent = message;
  $("#auth-sign-out").hidden = !signOut;
}

// Resolves true once the viewer is a signed-in administrator (or sign-in is disabled).
async function authorize() {
  let auth;
  try {
    auth = await window.appAuth.load();
  } catch (error) {
    gate(`Sign-in could not be loaded: ${error.message} Reload the page to try again.`);
    return false;
  }
  if (!auth.enabled) return true;
  if (!auth.configured) {
    gate("Sign-in is not set up on this server. Set CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY, then restart it.");
    return false;
  }
  const clerk = auth.clerk;
  // Start over whenever the signed-in user changes (sign-in, sign-out, account switch).
  const userId = clerk.user?.id || null;
  clerk.addListener(({ user }) => { if ((user?.id || null) !== userId) location.reload(); });
  $("#auth-sign-out").onclick = () => clerk.signOut();
  if (!userId) {
    gate("Sign in with an administrator account to continue.");
    clerk.mountSignIn($("#auth-gate-widget"), { forceRedirectUrl: location.href, signUpForceRedirectUrl: location.href });
    return false;
  }
  let me;
  try {
    me = await request("/auth/me");
  } catch (error) {
    gate(`Could not check your access: ${error.message}`, { signOut: true });
    return false;
  }
  if (!me.admin) {
    gate("This account is not an administrator. An administrator must set \"admin\": true in its Clerk public metadata.", { signOut: true });
    return false;
  }
  clerk.mountUserButton($("#user-button"));
  $("#user-button").hidden = false;
  return true;
}

queryControls();
authorize().then((allowed) => {
  if (!allowed) return;
  $("#auth-gate").hidden = true;
  window.addEventListener("hashchange", showView);
  showView();
  loadHealth();
});
