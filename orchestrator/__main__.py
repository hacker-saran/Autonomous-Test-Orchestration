"""CLI entrypoint: python -m orchestrator run --url ... --prd ... --focus "..." """
from __future__ import annotations

import argparse
import json
import logging
import sys

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

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
