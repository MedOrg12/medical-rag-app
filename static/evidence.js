"use strict";

// Shared, escaped rendering for generated text and indexed evidence in both views.
window.EvidenceUI = (() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const idsIn = (group) => group.split(/\s*[,;]\s*/).flatMap((part) => {
    const [first, last = first] = part.split(/\s*-\s*/).map(Number);
    return last >= first && last - first <= 100
      ? Array.from({ length: last - first + 1 }, (_, index) => first + index)
      : [first, last];
  });

  function inline(text, citations, prefix) {
    return esc(text).replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[(\d+(?:\s*-\s*\d+)?(?:\s*[,;]\s*\d+(?:\s*-\s*\d+)?)*)\]/g, (_, group) => idsIn(group).map((id) => {
        if (!citations.some((citation) => citation.id === id)) {
          return `<span class="citation-invalid" title="This source number was not provided">[${id}]</span>`;
        }
        return `<button type="button" class="citation-link citation" data-source="${prefix}-${id}" aria-label="Read source ${id}" title="Read source ${id}">[${id}]</button>`;
      }).join(" "));
  }

  function answer(text, citations, prefix) {
    const blocks = [];
    let paragraph = [];
    let list = [];
    let listType = "";
    let listStart = 1;
    const render = (value) => inline(value, citations, prefix);
    const flushParagraph = () => {
      if (paragraph.length) blocks.push(`<p>${render(paragraph.join(" "))}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (list.length) blocks.push(`<${listType}${listType === "ol" ? ` start="${listStart}"` : ""}>${list.map((item) => `<li>${render(item)}</li>`).join("")}</${listType}>`);
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
        if (heading) blocks.push(`<h2>${render(heading[1])}</h2>`);
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

  function sources(citations, prefix, scores = false) {
    return citations.map((c) => {
      const id = Number(c.id);
      const pages = c.page != null
        ? `PDF page${c.page_end > c.page ? `s ${c.page}-${c.page_end}` : ` ${c.page}`}`
        : "Page not recorded";
      const bibliography = [c.publisher || "Publisher not recorded", c.publication_date || c.publication_year || "Year not recorded", pages];
      const safeUrl = typeof c.document_url === "string" && /^\/evidence\/[^/?#]+\/document(?:#page=[1-9]\d*)?$/.test(c.document_url);
      return `<article class="evidence-item" id="${prefix}-${id}" tabindex="-1">
        <h3 class="source-title">[${id}] ${esc(c.title || c.source || "Unknown source")}</h3>
        <p class="source-page">${bibliography.map(esc).join(" · ")}</p>
        <p class="source-curation"><span class="evidence-tag">${esc((c.document_type || "unclassified").replaceAll("_", " "))}</span><span class="evidence-tag status-${["current", "superseded", "withdrawn"].includes(c.status) ? c.status : "unreviewed"}">${esc(c.status && c.status !== "unreviewed" ? c.status : "Metadata unreviewed")}</span></p>
        ${c.populations?.length ? `<p class="source-population">Population: ${esc(c.populations.join(", "))}</p>` : ""}
        ${c.topics?.length ? `<p class="source-topics">Topics: ${esc(c.topics.join(", "))}</p>` : ""}
        ${c.jurisdiction || c.document_version ? `<p class="source-context">${esc([c.jurisdiction, c.document_version ? `Version ${c.document_version}` : null].filter(Boolean).join(" · "))}</p>` : ""}
        ${["superseded", "withdrawn"].includes(c.status) ? `<p class="evidence-warning">Historical source: ${esc(c.status)}. ${esc(c.review_notes || "")}${c.superseded_by ? ` Replaced by ${esc(c.superseded_by)}.` : ""}</p>` : ""}
        ${c.title && c.source ? `<p class="source-filename">${esc(c.source)}</p>` : ""}
        ${c.section ? `<p class="source-section">${esc(c.section)}</p>` : ""}
        ${scores ? `<p class="evidence-metrics">Retrieval score ${esc(c.score ?? "-")}</p>` : ""}
        <p class="source-excerpt">${esc(c.excerpt || c.text || "No passage text available.")}</p>
        ${c.text ? `<details class="full-passage"><summary>Full indexed passage</summary><blockquote>${esc(c.text)}</blockquote></details>` : ""}
        ${safeUrl ? `<a class="source-document" href="${esc(c.document_url)}" target="_blank" rel="noopener noreferrer">Open original PDF${c.page ? `, page ${esc(c.page)}` : ""}<svg aria-hidden="true"><use href="/static/icons.svg#arrow-up-right"></use></svg></a>` : '<p class="source-unavailable">Original PDF unavailable</p>'}
      </article>`;
    }).join("");
  }

  function warnings(validation) {
    return (validation?.warnings || []).map((warning) => `<p class="evidence-warning" role="status">${esc(warning)}</p>`).join("");
  }

  function conflicts(items, prefix) {
    if (!items.length) return "";
    return `<section class="source-conflicts" aria-label="Source disagreements"><h2>Source Disagreements</h2>${items.map((item) => {
      const references = (ids) => ids?.length ? inline(`Retrieved passages ${ids.map((id) => `[${id}]`).join(" ")}`, ids.map((id) => ({id})), prefix) : "Source text not retrieved";
      return `<article class="source-conflict"><h3>${esc(item.topic)}</h3><p class="evidence-review-note">Curator-recorded comparison; claim support requires review.</p><div class="conflict-positions">
        <div><h4>${esc(item.source_title || item.source_id)}</h4><p>${esc(item.source_position)}</p><p class="evidence-review-note">${esc(item.source_status)}${item.source_page ? ` · Curator reference: PDF page ${esc(item.source_page)}` : ""}</p><p>${references(item.source_citation_ids)}</p></div>
        <div><h4>${esc(item.other_title || item.with_source)}</h4><p>${esc(item.other_position)}</p><p class="evidence-review-note">${esc(item.other_status)}${item.other_page ? ` · Curator reference: PDF page ${esc(item.other_page)}` : ""}</p><p>${references(item.other_citation_ids)}</p></div>
        </div><p class="conflict-context"><strong>Context:</strong> ${esc(item.context)}</p>${!item.both_sources_retrieved ? '<p class="evidence-warning">Both source texts were not retrieved for this answer. The recorded disagreement has not been checked against both documents.</p>' : ""}</article>`;
    }).join("")}</section>`;
  }

  return { answer, sources, warnings, conflicts };
})();
