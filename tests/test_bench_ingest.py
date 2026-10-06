import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "bench_ingest", Path(__file__).resolve().parent.parent / "scripts" / "bench_ingest.py"
)
bench = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bench)


def test_last_json_object_skips_diagnostics_before_the_report(tmp_path) -> None:
    log = tmp_path / "ingest.out"
    log.write_text('--- GPU visibility ---\n{"not": "the report"}\nmore\n{\n  "chunks": 3,\n  "timings": {}\n}\n')

    assert bench._last_json_object(log) == {"chunks": 3, "timings": {}}
    assert bench._last_json_object(tmp_path / "missing.out") is None


def test_endpoint_micros_reads_rest_and_grpc_telemetry() -> None:
    snapshot = {
        "telemetry": {
            "requests": {
                "rest": {
                    "responses": {
                        "PUT /collections/{collection_name}/points": {
                            "200": {"count": 2, "total_duration_micros": 3000},
                            "400": {"count": 1, "avg_duration_micros": 500.0},
                        }
                    }
                },
                "grpc": {"responses": {"/qdrant.Points/Upsert": {"count": 1, "total_duration_micros": 1000}}},
            }
        }
    }

    assert bench._endpoint_micros(snapshot, bench.UPSERT_ENDPOINTS) == 4500


def test_job_row_reads_new_and_old_reports(tmp_path) -> None:
    new_dir, old_dir = tmp_path / "new", tmp_path / "old"
    new_dir.mkdir()
    old_dir.mkdir()
    (new_dir / "ingest.out").write_text(
        json.dumps(
            {
                "chunks_embedded": 10,
                "timings": {
                    "total_seconds": 50.0,
                    "discovery_seconds": 4.0,
                    "manifest_seconds": 2.0,
                    "embedding_seconds": 20.0,
                    "reuse_lookup_seconds": 1.0,
                },
                "vector_store": {
                    "total_seconds": 30.0,
                    "write_wait_seconds": 5.0,
                    "setup_seconds": 1.0,
                    "point_build_seconds": 2.0,
                    "cleanup_seconds": 1.0,
                    "upsert_busy_seconds": 12.0,
                    "upsert_requests": 3,
                },
            },
            indent=2,
        )
    )
    (old_dir / "ingest.out").write_text(
        json.dumps({"timings": {"total_seconds": 90.0, "embedding_seconds": 20.0, "index_write_seconds": 40.0}}, indent=2)
    )
    (old_dir / "job.json").write_text('{"exit_code": 0, "wall_seconds": 95}')

    new = bench._job_row({"index": 0, "label": "new", "params": {}, "job_dir": str(new_dir), "collection": "c"}, {})
    old = bench._job_row({"index": 1, "label": "old", "params": {}, "job_dir": str(old_dir), "collection": "c"}, {})

    assert (new["state"], new["vector_s"], new["write_other_s"], new["upsert_requests"]) == ("OK", 30.0, 4.0, 3)
    assert (old["state"], old["vector_s"], old["write_wait_s"]) == ("OK", 60.0, 40.0)
    assert (new["discovery_s"], new["manifest_s"], new["chunking_s"]) == (4.0, 2.0, "-")
    assert (old["job_wall_s"], old["manifest_s"]) == (95.0, "-")


def test_job_row_marks_failed_jobs(tmp_path) -> None:
    (tmp_path / "job.json").write_text('{"exit_code": 1, "wall_seconds": 5}')

    row = bench._job_row({"index": 0, "label": "x", "params": {}, "job_dir": str(tmp_path), "collection": "c"}, {})

    assert row["state"] == "FAILED(1)" and row["ok"] is False


def test_summary_takes_medians_and_ratios_against_the_first_commit() -> None:
    rows = [
        {"params_text": "p", "label": "old", "ok": True, "total_s": 100.0, "vector_s": 80.0},
        {"params_text": "p", "label": "old", "ok": True, "total_s": 120.0, "vector_s": 90.0},
        {"params_text": "p", "label": "new", "ok": True, "total_s": 55.0, "vector_s": 40.0},
        {"params_text": "p", "label": "new", "ok": False},
    ]

    old, new = bench._summarize(rows, ["old", "new"])

    assert (old["total_s"], old["ratio"], old["ok"]) == (110.0, "1.00x", "2/2")
    assert (new["total_s"], new["ratio"], new["ok"]) == (55.0, "0.50x", "1/2")


def test_submit_dry_run_alternates_commit_order_between_repeats(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(bench, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(bench, "_resolve_commit", lambda ref: {"label": ref, "ref": ref, "sha": ref * 12})

    bench.main(
        ["submit", "--commit", "a", "--commit", "b", "--corpus", str(tmp_path), "--repeats", "2",
         "--sweep", "RAG_QDRANT_BATCH_SIZE=256,1024", "--dry-run"]
    )

    lines = [line.split() for line in capsys.readouterr().out.splitlines() if line.startswith("  0")]
    assert [(label, params) for _, label, params in lines] == [
        ("a", "QDRANT_BATCH_SIZE=256"), ("b", "QDRANT_BATCH_SIZE=256"),
        ("a", "QDRANT_BATCH_SIZE=1024"), ("b", "QDRANT_BATCH_SIZE=1024"),
        ("b", "QDRANT_BATCH_SIZE=256"), ("a", "QDRANT_BATCH_SIZE=256"),
        ("b", "QDRANT_BATCH_SIZE=1024"), ("a", "QDRANT_BATCH_SIZE=1024"),
    ]
    assert not (tmp_path / "runs").exists()


def test_parse_assignment_rejects_missing_value() -> None:
    with pytest.raises(SystemExit):
        bench._parse_assignment("NOEQUALS")
