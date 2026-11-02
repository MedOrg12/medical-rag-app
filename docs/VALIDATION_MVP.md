# Validation rollout

## Choosing a screening provider

The developer dashboard's Documents tab supports OpenAI and Gemini for individual
PDF scans. The selector changes that scan only. The default for scans, CLI validation
and screening during ingestion is controlled by `RAG_VALIDATION_PROVIDER`:

```dotenv
RAG_VALIDATION_PROVIDER=openai
RAG_VALIDATION_OPENAI_MODEL=gpt-4o-mini
RAG_VALIDATION_GEMINI_MODEL=gemini-3.1-flash-lite
```

OpenAI uses `OPENAI_API_KEY` (or `RAG_VALIDATION_OPENAI_API_KEY`); Gemini uses
`GEMINI_API_KEY` (or `RAG_VALIDATION_GEMINI_API_KEY`). Keep credentials in the
server's local environment. Gemini native transport and OpenAI structured JSON
output remain available. A missing key blocks a requested UI scan rather than
silently using the other provider. Provider selection does not change answer generation.

`configured` preserves the existing shared/custom endpoint settings. Saved
assessments include the provider endpoint and model in their cache key, so an OpenAI
scan does not reuse Gemini assessments. Existing audits and reviews are retained.

The historical rollout and corpus measurements below used Gemini.

The implementation supports off, report-only and enforced screening for JSON and
Qdrant, with no-vector-write dry runs, audit records, versioned assessments and a
manual review queue. The local rollout selects report-only mode, Gemini 3.1
Flash-Lite through native Gemini transport, two workers, a 5,000-character abstract
limit and the existing 0.7 confidence threshold. These local settings are in the
ignored `.env`; credentials must remain there.

The extraction update fixes structured abstracts beginning with Introduction,
inline keyword boundaries, translated-summary boundaries, layout pipes, and
publisher metadata. It recognizes complete structured summaries without a literal
Abstract heading. Fragmented or unfinished abstracts remain in review.

## Evidence and limits

- Local automated tests cover schema failures, provider retries, cache invalidation,
  manual reviews, extraction, both storage backends and index preservation.
- The live model returned a schema-valid relevance decision on a real abstract.
- Corpus and reference-run results are kept under `logs/validation-runs/` and in
  `.rag/abstract_validation.sqlite`; they are local artifacts, excluded from Git.
- The 20 reference labels are explicitly assistant-reviewed. They help detect obvious
  classification regressions, but do not replace independent clinical adjudication
  or establish a statistically calibrated threshold.
- A circuit breaker defers new provider calls after three exhausted operational
  failures in a batch, while finishing local extraction and retaining cached results.
- The model may still have intermittent provider failures. These remain retryable;
  they are not rejections, approvals or permanent cached assessments.
- Missing and incomplete abstracts cannot be approved by inference from file names.
  Their original PDFs need review or an explicitly approved extraction/OCR workflow.

## Operating the review queue

Use the same index path as the app:

```sh
venv/bin/python -m medical_rag.cli --index .rag/index.json review list --limit 50
venv/bin/python -m medical_rag.cli --index .rag/index.json review list --reason-code incomplete_abstract
venv/bin/python -m medical_rag.cli --index .rag/index.json review show REVIEW_ID
venv/bin/python -m medical_rag.cli --index .rag/index.json review approve REVIEW_ID --reviewer "Reviewer" --reason "Evidence from original PDF"
venv/bin/python -m medical_rag.cli --index .rag/index.json review retry REVIEW_ID
```

Approval only affects eligibility during the next ingestion. It does not write
vectors. Report-only mode deliberately continues ordinary ingestion; change to
enforce only after reviewing the results. In enforce mode an operational validation
outage stops ingestion before vector-store writes.

## Local run, October 22, 2026

The completed pass covered all 1,545 PDFs without changing the vector index:

| Outcome | PDFs |
|---|---:|
| Gemini accepted | 48 |
| Gemini rejected | 1 |
| Provider failure/deferred | 518 |
| No reliable abstract | 766 |
| Incomplete abstract/layout fragment | 187 |
| Abstract exceeds 5,000 characters | 25 |

The 20-case reference check had nine comparable model decisions, all matching the
assistant reference labels, with zero false accepts in those nine cases. Four
structural review cases were held correctly. Seven classification cases were
deferred; these results do not justify enforcement or a calibrated threshold.
The threshold remains 0.7 in report-only mode.

The completed local reports are `logs/validation-runs/20261022-gemini-validation.json`
and `logs/validation-runs/20261022-quality-check.json`. These and the review database
contain corpus data and are intentionally excluded from Git. Re-running validation
reuses the 49 completed assessments and retries operational failures.
