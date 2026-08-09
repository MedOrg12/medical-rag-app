#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from medical_rag.config import Settings  # noqa: E402
from medical_rag.documents import iter_source_files  # noqa: E402
from medical_rag.pipeline import StrokeRAG  # noqa: E402


@dataclass(frozen=True)
class BenchmarkResult:
    scenario: str
    run: int
    wall_seconds: float
    report: dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    base_settings = _base_settings(args)

    with _benchmark_workspace(args.work_dir) as workspace:
        effective_source, source_files = _prepare_source(
            source=args.source,
            max_files=args.max_files,
            workspace=workspace,
        )

        print(f"Benchmark source: {effective_source}")
        if effective_source != args.source.expanduser().resolve():
            print(f"Original source:  {args.source.expanduser().resolve()}")
        print(f"Files measured:   {len(source_files)}")
        print(f"Runs:             {args.runs}")
        print(f"Embedding:        {base_settings.embedding_backend}")
        print(f"New PDF workers:  {base_settings.pdf_workers}")
        print(f"Embed batch size: {base_settings.embedding_batch_size}")
        print()

        results = _run_benchmark(
            base_settings=base_settings,
            source=effective_source,
            workspace=workspace,
            runs=args.runs,
            skip_cached_rebuild=args.skip_cached_rebuild,
        )

        summary = _summarize(results)
        _print_summary(summary)

        if args.json_output is not None:
            _write_json_output(
                path=args.json_output,
                args=args,
                workspace=workspace,
                source=effective_source,
                source_files=source_files,
                settings=base_settings,
                results=results,
                summary=summary,
            )

        if args.work_dir is not None:
            print(f"\nBenchmark artifacts kept under: {workspace}")

    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark legacy full ingestion against the newer manifest/cache-backed ingestion path."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("pdfs"),
        help="Corpus file or directory to benchmark. Defaults to ./pdfs.",
    )
    parser.add_argument("--runs", type=int, default=3, help="Timed runs per scenario.")
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Benchmark only the first N supported files, using a temporary symlinked corpus.",
    )
    parser.add_argument(
        "--pdf-workers",
        type=int,
        default=None,
        help="PDF extraction workers for the new incremental path.",
    )
    parser.add_argument(
        "--embed-batch-size",
        type=int,
        default=None,
        help="Embedding cache miss batch size for the new incremental path.",
    )
    parser.add_argument(
        "--embedding-backend",
        choices=["hash", "ollama"],
        default=None,
        help="Override RAG_EMBEDDING_BACKEND for the benchmark.",
    )
    parser.add_argument(
        "--chunk-size-chars",
        type=int,
        default=None,
        help="Override chunk size for the benchmark.",
    )
    parser.add_argument(
        "--chunk-overlap-chars",
        type=int,
        default=None,
        help="Override chunk overlap for the benchmark.",
    )
    parser.add_argument(
        "--skip-cached-rebuild",
        action="store_true",
        help="Skip the incremental cached index rebuild scenario.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help=(
            "Directory where benchmark artifacts should be kept. "
            "By default, artifacts are written to a temporary directory and removed."
        ),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path for machine-readable benchmark results.",
    )

    args = parser.parse_args(argv)
    if args.runs <= 0:
        parser.error("--runs must be greater than zero")
    if args.max_files is not None and args.max_files <= 0:
        parser.error("--max-files must be greater than zero")
    if args.pdf_workers is not None and args.pdf_workers <= 0:
        parser.error("--pdf-workers must be greater than zero")
    if args.embed_batch_size is not None and args.embed_batch_size <= 0:
        parser.error("--embed-batch-size must be greater than zero")
    if args.chunk_size_chars is not None and args.chunk_size_chars <= 0:
        parser.error("--chunk-size-chars must be greater than zero")
    if args.chunk_overlap_chars is not None and args.chunk_overlap_chars < 0:
        parser.error("--chunk-overlap-chars cannot be negative")
    if (
        args.chunk_size_chars is not None
        and args.chunk_overlap_chars is not None
        and args.chunk_overlap_chars >= args.chunk_size_chars
    ):
        parser.error("--chunk-overlap-chars must be smaller than --chunk-size-chars")
    return args


def _base_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env(root_dir=REPO_ROOT)
    updates: dict[str, Any] = {}
    if args.embedding_backend is not None:
        updates["embedding_backend"] = args.embedding_backend
    if args.pdf_workers is not None:
        updates["pdf_workers"] = args.pdf_workers
    if args.embed_batch_size is not None:
        updates["embedding_batch_size"] = args.embed_batch_size
    if args.chunk_size_chars is not None:
        updates["chunk_size_chars"] = args.chunk_size_chars
    if args.chunk_overlap_chars is not None:
        updates["chunk_overlap_chars"] = args.chunk_overlap_chars
    return replace(settings, **updates) if updates else settings


@contextmanager
def _benchmark_workspace(work_dir: Path | None) -> Iterator[Path]:
    if work_dir is not None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        workspace = work_dir.expanduser().resolve() / f"ingestion-benchmark-{timestamp}"
        workspace.mkdir(parents=True, exist_ok=False)
        yield workspace
        return

    with tempfile.TemporaryDirectory(prefix="medical-rag-ingestion-benchmark-") as temp_dir:
        yield Path(temp_dir)


def _prepare_source(
    source: Path,
    max_files: int | None,
    workspace: Path,
) -> tuple[Path, list[Path]]:
    source = source.expanduser().resolve()
    files = iter_source_files(source)
    if not files:
        raise ValueError(f"No supported source files found under {source}")

    if max_files is None or len(files) <= max_files:
        return source, files

    selected = files[:max_files]
    subset_dir = workspace / "corpus_subset"
    subset_dir.mkdir(parents=True, exist_ok=True)
    for index, source_file in enumerate(selected, start=1):
        target = subset_dir / f"{index:04d}_{source_file.name}"
        try:
            target.symlink_to(source_file)
        except OSError:
            shutil.copy2(source_file, target)
    return subset_dir, selected


def _run_benchmark(
    base_settings: Settings,
    source: Path,
    workspace: Path,
    runs: int,
    skip_cached_rebuild: bool,
) -> list[BenchmarkResult]:
    results: list[BenchmarkResult] = []

    for run in range(1, runs + 1):
        legacy_dir = workspace / f"run-{run}" / "legacy-full"
        legacy_settings = _legacy_settings(base_settings, source, legacy_dir)
        results.append(_time_ingest("legacy_full_ingest", run, legacy_settings, source))

        incremental_dir = workspace / f"run-{run}" / "incremental"
        incremental_settings = _incremental_settings(base_settings, source, incremental_dir)
        results.append(_time_ingest("incremental_cold_ingest", run, incremental_settings, source))

        resume_settings = _incremental_settings(base_settings, source, incremental_dir)
        results.append(_time_ingest("incremental_resume_noop", run, resume_settings, source))

        if not skip_cached_rebuild:
            cached_rebuild_settings = replace(
                resume_settings,
                index_path=incremental_dir / ".rag" / "rebuilt-from-cache-index.json",
            )
            results.append(
                _time_ingest(
                    "incremental_cached_rebuild",
                    run,
                    cached_rebuild_settings,
                    source,
                )
            )

    return results


def _legacy_settings(base_settings: Settings, source: Path, run_dir: Path) -> Settings:
    return replace(
        base_settings,
        corpus_dir=source,
        index_path=run_dir / ".rag" / "index.json",
        embedding_cache_path=None,
        manifest_path=None,
        extraction_cache_dir=None,
    )


def _incremental_settings(base_settings: Settings, source: Path, run_dir: Path) -> Settings:
    rag_dir = run_dir / ".rag"
    return replace(
        base_settings,
        corpus_dir=source,
        index_path=rag_dir / "index.json",
        embedding_cache_path=rag_dir / "embedding_cache.json",
        manifest_path=rag_dir / "manifest.sqlite",
        extraction_cache_dir=rag_dir / "extracted",
    )


def _time_ingest(
    scenario: str,
    run: int,
    settings: Settings,
    source: Path,
) -> BenchmarkResult:
    print(f"[run {run}] {scenario} ...", flush=True)
    gc.collect()
    started = time.perf_counter()
    rag = StrokeRAG(settings)
    report = rag.ingest(source)
    elapsed = time.perf_counter() - started
    print(f"[run {run}] {scenario}: {elapsed:.3f}s ({_report_counts(report.to_dict())})")
    return BenchmarkResult(
        scenario=scenario,
        run=run,
        wall_seconds=round(elapsed, 6),
        report=report.to_dict(),
    )


def _report_counts(report: dict[str, Any]) -> str:
    return (
        f"docs={report.get('documents')}, pages={report.get('pages')}, "
        f"chunks={report.get('chunks')}, skipped={report.get('skipped_unchanged')}"
    )


def _summarize(results: list[BenchmarkResult]) -> list[dict[str, Any]]:
    grouped: dict[str, list[BenchmarkResult]] = {}
    for result in results:
        grouped.setdefault(result.scenario, []).append(result)

    summary: list[dict[str, Any]] = []
    for scenario, items in grouped.items():
        seconds = [item.wall_seconds for item in items]
        first_report = items[0].report
        summary.append(
            {
                "scenario": scenario,
                "runs": len(items),
                "mean_seconds": round(mean(seconds), 6),
                "median_seconds": round(median(seconds), 6),
                "min_seconds": round(min(seconds), 6),
                "max_seconds": round(max(seconds), 6),
                "documents": first_report.get("documents"),
                "pages": first_report.get("pages"),
                "chunks": first_report.get("chunks"),
            }
        )
    return summary


def _print_summary(summary: list[dict[str, Any]]) -> None:
    baseline = next(
        item["mean_seconds"] for item in summary if item["scenario"] == "legacy_full_ingest"
    )

    rows = []
    for item in summary:
        speedup = baseline / item["mean_seconds"] if item["mean_seconds"] else float("inf")
        rows.append(
            [
                item["scenario"],
                str(item["runs"]),
                f"{item['mean_seconds']:.3f}",
                f"{item['median_seconds']:.3f}",
                f"{item['min_seconds']:.3f}",
                f"{item['max_seconds']:.3f}",
                f"{speedup:.2f}x",
                str(item["chunks"]),
            ]
        )

    print("\nSummary")
    _print_table(
        headers=[
            "scenario",
            "runs",
            "mean_s",
            "median_s",
            "min_s",
            "max_s",
            "vs_legacy",
            "chunks",
        ],
        rows=rows,
    )
    print(
        "\nNotes: legacy_full_ingest disables manifest, extraction cache, and embedding cache. "
        "incremental_resume_noop measures a clean app object seeing an unchanged corpus and "
        "existing index. Results include normal OS file-cache effects."
    )


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    header_line = "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    divider = "  ".join("-" * width for width in widths)
    print(header_line)
    print(divider)
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _write_json_output(
    path: Path,
    args: argparse.Namespace,
    workspace: Path,
    source: Path,
    source_files: list[Path],
    settings: Settings,
    results: list[BenchmarkResult],
    summary: list[dict[str, Any]],
) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "source": str(source),
        "source_files": [str(file) for file in source_files],
        "args": {
            "runs": args.runs,
            "max_files": args.max_files,
            "skip_cached_rebuild": args.skip_cached_rebuild,
        },
        "settings": {
            "chunk_size_chars": settings.chunk_size_chars,
            "chunk_overlap_chars": settings.chunk_overlap_chars,
            "embedding_backend": settings.embedding_backend,
            "hash_embedding_dimensions": settings.hash_embedding_dimensions,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_embedding_model": settings.ollama_embedding_model,
            "pdf_workers": settings.pdf_workers,
            "embedding_batch_size": settings.embedding_batch_size,
        },
        "summary": summary,
        "results": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote JSON results to: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
