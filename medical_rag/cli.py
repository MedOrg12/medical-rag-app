from __future__ import annotations

import argparse
import json
from pathlib import Path

from medical_rag.config import Settings
from medical_rag.pipeline import StrokeRAG


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stroke-rag")
    parser.add_argument("--index", type=Path, help="Path to the vector index JSON file.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest PDFs/text into the vector index.")
    ingest_parser.add_argument("--source", type=Path, help="File or directory to ingest.")

    ask_parser = subparsers.add_parser("ask", help="Ask a question against the indexed corpus.")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--top-k", type=int, default=None)
    ask_parser.add_argument(
        "--mode",
        choices=["patient", "clinician"],
        default=None,
        help="Answer style: patient is plain language; clinician is more technical.",
    )
    ask_parser.add_argument("--json", action="store_true", help="Print the full JSON response.")

    serve_parser = subparsers.add_parser("serve", help="Run the FastAPI server.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.index:
        settings = settings.with_paths(index_path=args.index.expanduser().resolve())

    if args.command == "serve":
        import uvicorn

        uvicorn.run("medical_rag.server:app", host=args.host, port=args.port, reload=False)
        return 0

    rag = StrokeRAG(settings)
    if args.command == "ingest":
        report = rag.ingest(args.source)
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    if args.command == "ask":
        response = rag.ask(args.question, top_k=args.top_k, answer_mode=args.mode)
        if args.json:
            print(json.dumps(response.to_dict(), indent=2))
        else:
            print(response.answer)
            if response.citations:
                print("\nCitations:")
                for citation in response.citations:
                    page = f", page {citation.page}" if citation.page is not None else ""
                    print(
                        f"[{citation.id}] {citation.source}{page} "
                        f"(score={citation.score:.3f})"
                    )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
