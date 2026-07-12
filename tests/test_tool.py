from __future__ import annotations

import json
from pathlib import Path

import pytest
from mythings.engine import EngineResult, NoopEngine
from mythings.github import GitHub, Issue
from mythings.ledger import Ledger, LedgerEntry
from mythings.policy import Action, Decision, PolicyResult
from mythings.testing import FakeGh, make_git_repo

from myequations.tool import LEDGER_KIND, TOOL, Result, Tool


def gh_for(issues: list[dict] | None = None) -> FakeGh:
    # The gh process is the only mocked boundary, mirroring the core tests.
    return FakeGh(
        {
            ("issue", "list"): json.dumps(issues or []),
            ("pr", "create"): "https://github.com/o/r/pull/7\n",
        }
    )


def issue_obj(number: int = 1, title: str = "do the thing") -> dict:
    return {
        "number": number,
        "title": title,
        "body": "details",
        "url": f"https://github.com/o/r/issues/{number}",
        "labels": [{"name": "my-equations"}],
    }


@pytest.fixture()
def clone(tmp_path: Path) -> Path:
    # A real repo with an origin/main ref, so Workspace's worktree dance runs
    # for real; only gh and the push-side git calls are faked.
    return make_git_repo(tmp_path, files={"README.md": "seed\n"}).path


def make_tool(clone: Path, tmp_path: Path, runner: FakeGh, **kwargs) -> tuple[Tool, list]:
    git_calls: list[tuple[Path, list[str]]] = []
    tool = kwargs.pop("cls", Tool)(
        repo=clone,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        github=GitHub("o/r", runner=runner),
        engine=NoopEngine(),
        git=lambda tree, argv: git_calls.append((tree, argv)),
        **kwargs,
    )
    return tool, git_calls


def ledger_entries(tmp_path: Path) -> list[LedgerEntry]:
    path = tmp_path / "ledger.jsonl"
    return [LedgerEntry.from_json(line) for line in path.read_text().splitlines()]


def test_run_skips_when_no_labeled_issue(clone: Path, tmp_path: Path) -> None:
    runner = gh_for(issues=[])
    tool, _ = make_tool(clone, tmp_path, runner)
    result = tool.run()
    assert result.outcome == "skipped"
    (entry,) = ledger_entries(tmp_path)
    assert (entry.tool, entry.kind, entry.outcome) == (TOOL, LEDGER_KIND, "skipped")


def test_run_is_a_safe_noop_by_default(clone: Path, tmp_path: Path) -> None:
    # The pristine template's apply() changes nothing, so `run --engine noop`
    # is an end-to-end dry run: no branch, no PR, one honest ledger entry.
    runner = gh_for(issues=[issue_obj()])
    tool, git_calls = make_tool(clone, tmp_path, runner)
    result = tool.run()
    assert result == Result(outcome="noop", detail="nothing to change for #1", issue=1)
    assert not git_calls
    assert not runner.saw("pr", "create")
    (entry,) = ledger_entries(tmp_path)
    assert entry.outcome == "noop"


class WritingTool(Tool):
    def apply(self, tree: Path, issue: Issue, result: EngineResult) -> str | None:
        (tree / "out.txt").write_text(result.text or "generated\n")
        return "out.txt"


def test_run_opens_a_draft_pr_when_apply_changes_something(clone: Path, tmp_path: Path) -> None:
    runner = gh_for(issues=[issue_obj(number=4)])
    tool, git_calls = make_tool(clone, tmp_path, runner, cls=WritingTool)
    result = tool.run(issue_number=4)
    assert result.outcome == "success"
    assert result.pr == 7
    ops = [argv[0] for _, argv in git_calls]
    assert ops == ["checkout", "add", "commit", "push"]
    create = next(c for c in runner.calls if c[:2] == ["pr", "create"])
    assert "--draft" in create
    assert "my-equations/4" in create
    (entry,) = [e for e in ledger_entries(tmp_path) if e.outcome == "success"]
    assert entry.data == {"issue": 4, "pr": 7}


def test_run_returns_none_for_unknown_issue_number(clone: Path, tmp_path: Path) -> None:
    runner = gh_for(issues=[issue_obj(number=4)])
    tool, _ = make_tool(clone, tmp_path, runner)
    assert tool.run(issue_number=99).outcome == "skipped"


class AskPolicy:
    def evaluate(self, action: Action) -> PolicyResult:
        return PolicyResult(Decision.ASK, reason="needs a human")


def test_ask_fails_closed_unattended(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    runner = gh_for(issues=[issue_obj()])
    tool, git_calls = make_tool(clone, tmp_path, runner, cls=WritingTool, policy=AskPolicy())
    result = tool.run()
    assert result.outcome == "denied"
    assert not git_calls
    assert not runner.saw("pr", "create")
