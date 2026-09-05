"""CLI entrypoint: python -m orchestrator run --url ... --prd ... --focus "..." """
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from orchestrator.orchestrator import TestOrchestrator


def _load_credentials(path: str | None) -> dict | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrator", description="Autonomous Test Orchestration Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full pipeline against a target web app")
    run_parser.add_argument("--url", required=True, help="Target web app URL")
    run_parser.add_argument("--prd", default=None, help="Optional path to a PRD file")
    run_parser.add_argument("--focus", default=None, help="Optional natural-language focus hint")
    run_parser.add_argument("--credentials-file", default=None, help="Optional path to a JSON credentials file")
    run_parser.add_argument("--log-level", default="INFO", help="Python logging level (default: INFO)")

    serve_parser = subparsers.add_parser("serve", help="Launch the FastAPI dashboard server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_parser.add_argument("--reload", action="store_true", help="Enable uvicorn autoreload (development)")
    serve_parser.add_argument("--log-level", default="INFO", help="Python logging level (default: INFO)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "run":
        credentials = _load_credentials(args.credentials_file)
        orchestrator = TestOrchestrator()
        report = orchestrator.run(
            url=args.url,
            prd_path=args.prd,
            focus_hint=args.focus,
            credentials=credentials,
        )
        print(report.model_dump_json(indent=2))
        return 0

    if args.command == "serve":
        import uvicorn

        # --reload's default file-watch scope is the whole repo, which
        # includes directories the pipeline itself writes to *while a run is
        # in progress* (generated test files, dashboard/events.jsonl,
        # reports/*). Without narrowing the watch, every write during a run
        # triggers a server restart, killing that run's WebSocket
        # connections and its in-flight background thread mid-execution.
        # Reload should only ever be triggered by editing this package's own
        # source.
        reload_kwargs = (
            {
                "reload_dirs": [str(Path(__file__).resolve().parent)],
                "reload_excludes": [
                    "generated_tests/*",
                    "reports/*",
                    "*.jsonl",
                ],
            }
            if args.reload
            else {}
        )
        uvicorn.run(
            "orchestrator.web.server:app", host=args.host, port=args.port, reload=args.reload, **reload_kwargs,
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
