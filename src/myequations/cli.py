from __future__ import annotations

import argparse
from pathlib import Path

from mythings.engine import ClaudeCLIEngine, NoopEngine
from mythings.github import GitHub
from mythings.ledger import Ledger

from myequations.tool import BACKLOG_LABEL, Result, Tool


def _render(result: Result) -> str:
    line = f"{result.outcome}: {result.detail}"
    if result.issue is not None:
        line += f" (issue #{result.issue})"
    return line


def main(argv: list[str] | None = None, *, tool_factory: type[Tool] = Tool) -> int:
    parser = argparse.ArgumentParser(
        prog="myequations",
        description="Process one labeled issue: pre-work, one Engine call, a draft PR.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run the loop once against a single issue")
    run.add_argument("--issue", type=int, help="issue number (default: oldest with the label)")
    run.add_argument("--repo", help="GitHub slug owner/name (defaults to the local remote)")
    run.add_argument(
        "--source", type=Path, default=Path.cwd(), help="local git checkout to work in"
    )
    run.add_argument("--base", default="main", help="base branch for the PR")
    run.add_argument("--label", default=BACKLOG_LABEL, help="backlog label to pick issues from")
    run.add_argument("--ledger", type=Path, default=Path(".mythings/ledger.jsonl"))
    run.add_argument(
        "--engine",
        choices=("noop", "claude"),
        default="noop",
        help="noop replies with a fixed empty string (zero tokens); claude shells out to the CLI",
    )

    args = parser.parse_args(argv)
    tool = tool_factory(
        repo=args.source,
        ledger=Ledger(args.ledger),
        github=GitHub(args.repo),
        engine=NoopEngine() if args.engine == "noop" else ClaudeCLIEngine(),
        base=args.base,
        label=args.label,
    )
    result = tool.run(issue_number=args.issue)
    print(_render(result))
    return 0 if result.outcome not in ("failure", "denied") else 1


if __name__ == "__main__":
    raise SystemExit(main())
