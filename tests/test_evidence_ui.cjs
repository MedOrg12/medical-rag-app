const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../static/evidence.js"), "utf8"), context);
const ui = context.window.EvidenceUI;
const citations = [{ id: 2, title: "Example guideline", source: "guide.pdf", page: 3, page_end: 4, publisher: "Example society", publication_year: 2025, section: "Education", text: "The complete indexed passage.", excerpt: "The complete...", document_url: "/evidence/chunk-2/document#page=3" }];

test("clinician headings and citation references render without renumbering", () => {
  const html = ui.answer("## Bottom Line\nA finding [2].\n\n## Supporting Evidence\n- A detail [2].\n\n## Applicability and Limitations\nA gap.", citations, "query-evidence");
  assert.match(html, /<h2>Bottom Line<\/h2>/);
  assert.match(html, /data-source="query-evidence-2"/);
  assert.match(html, /<ul><li>A detail/);
  assert.doesNotMatch(html, /citation-invalid/);
});

test("citation groups expand and unavailable references are not linked", () => {
  const html = ui.answer("Findings [1, 2] [2-3].", citations, "query-evidence");
  assert.match(html, /citation-invalid[^>]*>\[1\]/);
  assert.match(html, /data-source="query-evidence-2"/);
  assert.doesNotMatch(html, /data-source="query-evidence-3"/);
});

test("full evidence contains bibliography, section, page range, and original PDF link", () => {
  const html = ui.sources(citations, "query-evidence");
  assert.match(html, /Example society · 2025 · PDF pages 3-4/);
  assert.match(html, /<blockquote>The complete indexed passage\.<\/blockquote>/);
  assert.match(html, /href="\/evidence\/chunk-2\/document#page=3"/);
  assert.match(html, /Education/);
  assert.doesNotMatch(html, /Retrieval score/);
});

test("missing metadata is explicit and hostile text or links cannot become executable", () => {
  const html = ui.sources([{ id: 2, title: '<img src=x onerror="alert(1)">', text: "<script>bad()</script>", document_url: "javascript:alert(1)" }], "safe");
  assert.match(html, /Publisher not recorded/);
  assert.match(html, /Year not recorded/);
  assert.match(html, /Original PDF unavailable/);
  assert.doesNotMatch(html, /<img|<script|href="javascript:/);
  assert.doesNotMatch(ui.answer('<img src=x onerror="alert(1)">', [], "safe"), /<img/);
  assert.doesNotMatch(ui.warnings({ warnings: ["<script>bad()</script>"] }), /<script>/);
});

test("curation labels and historical status do not imply automatic clinical verification", () => {
  const html = ui.sources([{...citations[0], document_type:"guideline", status:"superseded", review_notes:"Replaced by the publisher", populations:["adults"], jurisdiction:"Ontario", document_version:"2", superseded_by:"new.pdf"}], "safe");
  assert.match(html, /Historical source: superseded/);
  assert.match(html, /Population: adults/);
  assert.match(html, /Ontario · Version 2/);
  assert.match(html, /Replaced by new.pdf/);
});

test("disagreement context is escaped and missing source retrieval is explicit", () => {
  const html = ui.conflicts([{topic:"Reminders", source_id:"a.pdf", with_source:"b.pdf", source_position:"Daily reminders", other_position:"Weekly reminders", context:"<script>bad()</script>", source_status:"current", other_status:"unreviewed", source_citation_ids:[2], other_citation_ids:[], both_sources_retrieved:false}], "query-evidence");
  assert.match(html, /Curator-recorded comparison/);
  assert.match(html, /data-source="query-evidence-2"/);
  assert.match(html, /Source text not retrieved/);
  assert.match(html, /Both source texts were not retrieved/);
  assert.doesNotMatch(html, /<script>/);
  assert.equal(ui.conflicts([], "safe"), "");
});
