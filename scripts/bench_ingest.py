#!/usr/bin/env python3
"""Benchmark Qdrant ingestion across git commits on Slurm, and report the results.

    # Compare two commits, two repeats each, sweeping the upsert size:
    scripts/bench_ingest.py submit --commit 9a54a78 --commit HEAD \\
        --corpus ../stress-test-pdfs --repeats 2 --sweep RAG_QDRANT_BATCH_SIZE=256,1024 \\
        --env RAG_QDRANT_SSH_USER=fir_ssh_tunnel

    scripts/bench_ingest.py report            # latest run; re-run any time while jobs finish
    scripts/bench_ingest.py list

Each job checks its commit out into a git worktree under .bench/worktrees and runs that
commit's own scripts/slurm_ingest_qdrant.sbatch through scripts/bench_ingest_job.sbatch,
which gives every job a fresh collection, waits for Qdrant to be idle first, records
Qdrant telemetry around the run and deletes the collection afterwards. Jobs run one at a
time, alternating commit order between repeats, so drift in the shared Qdrant host's load
does not favour one commit. Only the standard library is used, so this runs on a login
node without the project's virtualenv.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO / ".bench"
RUNS_DIR = BENCH_DIR / "runs"
WORKTREES_DIR = BENCH_DIR / "worktrees"
JOB_SCRIPT = REPO / "scripts" / "bench_ingest_job.sbatch"

# Qdrant telemetry endpoint names, REST and gRPC, for the calls ingestion makes.
UPSERT_ENDPOINTS = ("PUT /collections/{collection_name}/points", "/qdrant.Points/Upsert")
RETRIEVE_ENDPOINTS = ("POST /collections/{collection_name}/points", "/qdrant.Points/Get")


# --- submit -------------------------------------------------------------------------------


def cmd_submit(args: argparse.Namespace) -> int:
    name = args.name or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / name
    if run_dir.exists():
        sys.exit(f"Run {name!r} already exists at {run_dir}")
    corpus = Path(args.corpus).resolve()
    if not corpus.is_dir():
        sys.exit(f"Corpus directory not found: {corpus}")

    commits = [_resolve_commit(ref) for ref in args.commit]
    fixed_env = dict(_parse_assignment(item) for item in args.env)
    sweep = [(key, values.split(",")) for key, values in map(_parse_assignment, args.sweep)]
    combos = [dict(zip([key for key, _ in sweep], values)) for values in itertools.product(*[v for _, v in sweep])]  # noqa: B905 - login nodes may predate 3.10

    jobs: list[dict[str, Any]] = []
    for repeat in range(args.repeats):
        for combo in combos:
            # ABBA ordering: alternate which commit goes first so slow drift cancels out.
            ordered = commits if repeat % 2 == 0 else list(reversed(commits))
            for commit in ordered:
                index = len(jobs)
                job_dir = run_dir / "jobs" / f"{index:03d}"
                jobs.append(
                    {
                        "index": index,
                        "label": commit["label"],
                        "sha": commit["sha"],
                        "repeat": repeat,
                        "params": combo,
                        "collection": f"bench_{_slug(name)}_{index:03d}",
                        "job_dir": str(job_dir),
                    }
                )

    plan = {
        "name": name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "runner": args.runner,
        "corpus": str(corpus),
        "commits": commits,
        "env": fixed_env,
        "sweep": dict(sweep),
        "repeats": args.repeats,
        "jobs": jobs,
    }
    print(f"Run {name}: {len(jobs)} jobs ({len(commits)} commits x {len(combos)} settings x {args.repeats} repeats)")
    for job in jobs:
        print(f"  {job['index']:03d}  {job['label']:<12} {_format_params(job['params'])}")
    if args.dry_run:
        return 0

    for commit in commits:
        _ensure_worktree(commit["sha"])
    run_dir.mkdir(parents=True)
    previous: str | None = None
    for job in jobs:
        job_dir = Path(job["job_dir"])
        job_dir.mkdir(parents=True)
        env_file = job_dir / "env.sh"
        env_file.write_text(_job_env_script(job, plan, fixed_env, corpus))
        if args.runner == "local":
            job["job_id"] = f"local-{job['index']}"
            _write_plan(run_dir, plan)
            print(f"running job {job['index']:03d} locally ...", flush=True)
            with open(job_dir / "slurm.out", "w") as out:
                subprocess.run(
                    ["bash", str(JOB_SCRIPT)],
                    env={**os.environ, "BENCH_ENV_FILE": str(env_file)},
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            continue
        command = [
            "sbatch",
            "--parsable",
            f"--export=ALL,BENCH_ENV_FILE={env_file}",
            f"--output={job_dir / 'slurm.out'}",
            f"--job-name=bench-{_slug(name)}-{job['index']:03d}",
            *([f"--dependency=afterany:{previous}"] if previous else []),
            *args.sbatch_arg,
            str(JOB_SCRIPT),
        ]
        job_id = subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
        job["job_id"] = previous = job_id.split(";")[0]
        print(f"  submitted {job['index']:03d} as {previous}")
    _write_plan(run_dir, plan)
    print(f"\nReport with: {Path(sys.argv[0]).name} report {name}")
    return 0


def _job_env_script(job: dict[str, Any], plan: dict[str, Any], fixed_env: dict[str, str], corpus: Path) -> str:
    job_dir = Path(job["job_dir"])
    env = {
        "BENCH_TOOL": str(Path(__file__).resolve()),
        "BENCH_WORKTREE": str(WORKTREES_DIR / job["sha"][:12]),
        "BENCH_JOB_DIR": str(job_dir),
        "RAG_CORPUS_DIR": str(corpus),
        # A fresh scratch dir per job so every job parses the corpus from cold, like the others.
        "RAG_SCRATCH_DIR": str(job_dir / "scratch"),
        "RAG_QDRANT_COLLECTION": job["collection"],
        "RAG_QDRANT_RECREATE_COLLECTION": "true",
        # Share one virtualenv and model cache instead of building one per worktree.
        "VENV_DIR": str(REPO / ".venv"),
        "HF_HOME": str(REPO / ".hf-cache"),
        **fixed_env,
        **job["params"],
    }
    return "".join(f"export {key}={shlex.quote(value)}\n" for key, value in env.items())


def _resolve_commit(ref: str) -> dict[str, str]:
    label, _, rev = ref.rpartition("=") if "=" in ref else ("", "", ref)
    sha = _git("rev-parse", "--verify", f"{rev}^{{commit}}")
    return {"label": label or sha[:8], "ref": rev, "sha": sha}


def _ensure_worktree(sha: str) -> None:
    path = WORKTREES_DIR / sha[:12]
    if not path.exists():
        WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
        _git("worktree", "add", "--detach", str(path), sha)


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout.strip()


def _parse_assignment(item: str) -> tuple[str, str]:
    key, sep, value = item.partition("=")
    if not sep or not key:
        sys.exit(f"Expected KEY=VALUE, got {item!r}")
    return key, value


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


def _write_plan(run_dir: Path, plan: dict[str, Any]) -> None:
    (run_dir / "plan.json").write_text(json.dumps(plan, indent=2))


# --- report -------------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = _run_dir(args.run)
    plan = json.loads((run_dir / "plan.json").read_text())
    states = _slurm_states([job["job_id"] for job in plan["jobs"] if not str(job.get("job_id", "")).startswith("local")])
    rows = [_job_row(job, states) for job in plan["jobs"]]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"Run {plan['name']}  corpus={plan['corpus']}  created={plan['created']}")
    print("Commits: " + ", ".join(f"{c['label']}={c['sha'][:12]}" for c in plan["commits"]))
    if plan["env"]:
        print("Env: " + _format_params(plan["env"]))
    print()
    columns = [
        ("#", "index"), ("commit", "label"), ("params", "params_text"), ("state", "state"),
        ("job_s", "job_wall_s"), ("total_s", "total_s"), ("disc_s", "discovery_s"),
        ("extract_s", "extraction_s"), ("chunk_s", "chunking_s"), ("manifest_s", "manifest_s"),
        ("vector_s", "vector_s"), ("lookup_s", "lookup_s"), ("embed_s", "embed_s"), ("wr_wait_s", "write_wait_s"), ("wr_other_s", "write_other_s"),
        ("upsert_busy_s", "upsert_busy_s"), ("srv_upsert_s", "server_upsert_s"),
        ("srv_io_mb", "server_io_write_mb"), ("reqs", "upsert_requests"),
        ("idle_wait_s", "idle_wait_s"), ("embedded", "chunks_embedded"),
    ]
    _print_table(columns, rows)

    print("\nSummary (median over successful jobs; ratio is total_s relative to the first commit)")
    summary = _summarize(rows, [c["label"] for c in plan["commits"]])
    _print_table(
        [("params", "params_text"), ("commit", "label"), ("ok", "ok"), ("total_s", "total_s"),
         ("range", "range"), ("job_s", "job_wall_s"), ("disc_s", "discovery_s"),
         ("chunk_s", "chunking_s"), ("manifest_s", "manifest_s"), ("vector_s", "vector_s"),
         ("embed_s", "embed_s"), ("wr_wait_s", "write_wait_s"), ("ratio", "ratio")],
        summary,
    )
    notes = _notes(rows)
    if notes:
        print("\nNotes:")
        for note in notes:
            print(f"  - {note}")
    return 0


def _job_row(job: dict[str, Any], states: dict[str, str]) -> dict[str, Any]:
    job_dir = Path(job["job_dir"])
    row: dict[str, Any] = {
        "index": f"{job['index']:03d}",
        "label": job["label"],
        "params": job["params"],
        "params_text": _format_params(job["params"]) or "-",
        "job_id": job.get("job_id"),
    }
    job_info = _read_json(job_dir / "job.json")
    report = _last_json_object(job_dir / "ingest.out")
    state = states.get(str(job.get("job_id")))
    if report is not None:
        state = "OK"
    elif job_info is not None:
        state = f"FAILED({job_info['exit_code']})"
    row["state"] = state or "PENDING?"
    if job_info is not None:
        # Whole job, including environment setup, model loading and work after the report.
        row["job_wall_s"] = _round(job_info["wall_seconds"])
    row["ok"] = report is not None

    if report is not None:
        timings = report.get("timings") or {}
        vector = report.get("vector_store") or {}
        row["total_s"] = timings.get("total_seconds")
        for stage in ("discovery", "extraction", "chunking", "manifest"):
            row[f"{stage}_s"] = timings.get(f"{stage}_seconds", "-")
        row["chunks_embedded"] = report.get("chunks_embedded", "-")
        row["embed_s"] = timings.get("embedding_seconds")
        row["lookup_s"] = timings.get("reuse_lookup_seconds", "-")
        if vector:
            row["vector_s"] = vector.get("total_seconds")
            row["write_wait_s"] = vector.get("write_wait_seconds")
            row["write_other_s"] = _round(
                sum(vector.get(f"{p}_seconds", 0.0) for p in ("setup", "point_build", "cleanup"))
            )
            row["upsert_busy_s"] = vector.get("upsert_busy_seconds")
            row["upsert_requests"] = vector.get("upsert_requests")
        else:
            # Older commits only split the vector store into embedding and writing, and ran
            # them one after the other, so their sum is the vector-store time.
            row["vector_s"] = _round(sum(timings.get(k, 0.0) for k in ("embedding_seconds", "index_write_seconds", "reuse_lookup_seconds")))
            row["write_wait_s"] = timings.get("index_write_seconds")

    before = _read_json(job_dir / "qdrant-before.json")
    after = _read_json(job_dir / "qdrant-after.json")
    if before and after:
        row["server_upsert_s"] = _round(_endpoint_micros(after, UPSERT_ENDPOINTS) - _endpoint_micros(before, UPSERT_ENDPOINTS), 1e-6)
        row["server_retrieve_s"] = _round(_endpoint_micros(after, RETRIEVE_ENDPOINTS) - _endpoint_micros(before, RETRIEVE_ENDPOINTS), 1e-6)
        row["server_io_write_mb"] = _round(_collection_io_write(after, job["collection"]), 1 / (1024 * 1024))
    idle = _read_json(job_dir / "qdrant-idle.json")
    if idle:
        row["idle_wait_s"] = idle.get("waited_seconds")
        row["idle_timed_out"] = idle.get("timed_out")
        row["busy_collections"] = idle.get("busy")
    return row


def _summarize(rows: list[dict[str, Any]], labels: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["params_text"], row["label"]), []).append(row)
    baseline: dict[str, float] = {}
    summary = []
    for params_text in dict.fromkeys(row["params_text"] for row in rows):
        for label in labels:
            group = groups.get((params_text, label), [])
            ok = [row for row in group if row["ok"]]
            entry: dict[str, Any] = {"params_text": params_text, "label": label, "ok": f"{len(ok)}/{len(group)}"}
            totals = [row["total_s"] for row in ok if isinstance(row.get("total_s"), (int, float))]
            if totals:
                entry["total_s"] = _round(statistics.median(totals))
                entry["range"] = f"{min(totals):.0f}-{max(totals):.0f}"
                for key in ("job_wall_s", "discovery_s", "chunking_s", "manifest_s", "vector_s", "embed_s", "write_wait_s"):
                    values = [row[key] for row in ok if isinstance(row.get(key), (int, float))]
                    entry[key] = _round(statistics.median(values)) if values else "-"
                baseline.setdefault(params_text, entry["total_s"])
                entry["ratio"] = f"{entry['total_s'] / baseline[params_text]:.2f}x"
            summary.append(entry)
    return summary


def _notes(rows: list[dict[str, Any]]) -> list[str]:
    notes = []
    for row in rows:
        if row.get("idle_timed_out"):
            notes.append(
                f"job {row['index']}: Qdrant was still busy when the job started "
                f"({', '.join(row.get('busy_collections') or [])}); its timings may be inflated."
            )
    return notes


def _endpoint_micros(snapshot: dict[str, Any], endpoints: tuple[str, ...]) -> float:
    requests = (snapshot.get("telemetry") or {}).get("requests") or {}
    total = 0.0
    for protocol in ("rest", "grpc"):
        responses = (requests.get(protocol) or {}).get("responses") or {}
        for endpoint in endpoints:
            stats = responses.get(endpoint) or {}
            # REST groups stats by status code; gRPC may not.
            for entry in [stats] if "count" in stats else stats.values():
                if isinstance(entry, dict):
                    total += entry.get("total_duration_micros") or entry.get("count", 0) * entry.get("avg_duration_micros", 0)
    return total


def _collection_io_write(snapshot: dict[str, Any], collection: str) -> float:
    data = (((snapshot.get("telemetry") or {}).get("hardware") or {}).get("collection_data") or {}).get(collection) or {}
    return float(sum(value for key, value in data.items() if key.endswith("_io_write")))


def _last_json_object(path: Path) -> dict[str, Any] | None:
    """The ingest CLI pretty-prints its report as the last top-level JSON object."""
    try:
        text = "\n" + path.read_text(errors="replace")
    except OSError:
        return None
    start = text.rfind("\n{\n")
    if start < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(text[start + 1 :])[0]
    except ValueError:
        return None


def _slurm_states(job_ids: list[str]) -> dict[str, str]:
    if not job_ids:
        return {}
    try:
        output = subprocess.run(
            ["sacct", "-X", "-n", "-P", "--format=JobID,State", "-j", ",".join(job_ids)],
            check=True, capture_output=True, text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    return dict(line.split("|", 1) for line in output.splitlines() if "|" in line)


def _run_dir(name: str | None) -> Path:
    if name:
        return RUNS_DIR / name
    runs = sorted(RUNS_DIR.glob("*/plan.json"), key=lambda p: p.stat().st_mtime)
    if not runs:
        sys.exit(f"No benchmark runs under {RUNS_DIR}")
    return runs[-1].parent


def cmd_list(args: argparse.Namespace) -> int:
    for plan_path in sorted(RUNS_DIR.glob("*/plan.json")):
        plan = json.loads(plan_path.read_text())
        commits = ", ".join(c["label"] for c in plan["commits"])
        print(f"{plan['name']:<20} {plan['created']}  {len(plan['jobs'])} jobs  [{commits}]")
    return 0


# --- helpers run inside the job (hidden subcommands) ----------------------------------------


def cmd_wait_idle(args: argparse.Namespace) -> int:
    """Wait until no collection is being optimized (status green or grey), so a previous
    job's background indexing does not slow this one down."""
    started = time.monotonic()
    busy: list[str] = []
    while True:
        busy = []
        for info in _qdrant(args.url, "GET", "/collections")["collections"]:
            status = _qdrant(args.url, "GET", f"/collections/{info['name']}").get("status")
            if status not in ("green", "grey"):
                busy.append(f"{info['name']}={status}")
        waited = time.monotonic() - started
        if not busy or waited >= args.timeout:
            break
        time.sleep(15)
    result = {"waited_seconds": round(waited, 1), "timed_out": bool(busy), "busy": busy}
    Path(args.out).write_text(json.dumps(result, indent=2))
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    snapshot: dict[str, Any] = {"time": time.time()}
    snapshot["telemetry"] = _qdrant(args.url, "GET", "/telemetry?details_level=1")
    try:
        snapshot["collection"] = _qdrant(args.url, "GET", f"/collections/{args.collection}")
    except urllib.error.HTTPError:
        snapshot["collection"] = None
    Path(args.out).write_text(json.dumps(snapshot, indent=2))
    return 0


def cmd_delete_collection(args: argparse.Namespace) -> int:
    _qdrant(args.url, "DELETE", f"/collections/{args.collection}?timeout=600", timeout=660)
    return 0


def _qdrant(url: str, method: str, path: str, timeout: float = 60) -> Any:
    request = urllib.request.Request(url.rstrip("/") + path, method=method)
    api_key = os.environ.get("RAG_QDRANT_API_KEY")
    if api_key:
        request.add_header("api-key", api_key)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read()).get("result")


# --- output helpers -------------------------------------------------------------------------


def _round(value: float, scale: float = 1.0) -> float:
    return round(value * scale, 1)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _format_params(params: dict[str, str]) -> str:
    return " ".join(f"{re.sub('^RAG_', '', key)}={value}" for key, value in params.items())


def _print_table(columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> None:
    def cell(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.1f}"
        return str(value)

    table = [[header for header, _ in columns]] + [[cell(row.get(key)) for _, key in columns] for row in rows]
    widths = [max(len(line[i]) for line in table) for i in range(len(columns))]
    for line in table:
        print("  ".join(value.ljust(width) for value, width in zip(line, widths)).rstrip())  # noqa: B905


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit", help="Submit a benchmark run.")
    submit.add_argument("--commit", action="append", required=True, help="Commit or ref, optionally LABEL=REF. Repeat to compare.")
    submit.add_argument("--corpus", required=True, help="Corpus directory every job ingests.")
    submit.add_argument("--repeats", type=int, default=2, help="Runs per commit and setting (default 2).")
    submit.add_argument("--sweep", action="append", default=[], metavar="KEY=A,B", help="Env var to sweep. Repeatable.")
    submit.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="Env var for every job. Repeatable.")
    submit.add_argument("--name", help="Run name (default: timestamp).")
    submit.add_argument("--sbatch-arg", action="append", default=[], help="Extra sbatch argument, e.g. --sbatch-arg=--time=06:00:00.")
    submit.add_argument("--runner", choices=("slurm", "local"), default="slurm", help="local runs jobs here, one by one, without Slurm.")
    submit.add_argument("--dry-run", action="store_true", help="Print the job plan without submitting.")
    submit.set_defaults(func=cmd_submit)

    report = sub.add_parser("report", help="Report a run (default: the latest).")
    report.add_argument("run", nargs="?")
    report.add_argument("--json", action="store_true", help="Print per-job rows as JSON.")
    report.set_defaults(func=cmd_report)

    sub.add_parser("list", help="List benchmark runs.").set_defaults(func=cmd_list)

    for name, func in (("_wait-idle", cmd_wait_idle), ("_snapshot", cmd_snapshot), ("_delete-collection", cmd_delete_collection)):
        hidden = sub.add_parser(name)
        hidden.add_argument("--url", required=True)
        hidden.add_argument("--collection", required=True)
        hidden.add_argument("--out")
        hidden.add_argument("--timeout", type=float, default=1800)
        hidden.set_defaults(func=func)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
