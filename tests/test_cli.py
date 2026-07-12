from __future__ import annotations

from pathlib import Path

import pytest
from mythings.engine import ClaudeCLIEngine, NoopEngine

from myequations.cli import main
from myequations.tool import Result


class SpyTool:
    instances: list[SpyTool] = []
    result = Result(outcome="noop", detail="nothing to change for #1", issue=1)

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        SpyTool.instances.append(self)

    def run(self, issue_number: int | None = None) -> Result:
        self.issue_number = issue_number
        return self.result


@pytest.fixture(autouse=True)
def _reset_spy() -> None:
    SpyTool.instances = []
    SpyTool.result = Result(outcome="noop", detail="nothing to change for #1", issue=1)


def test_run_wires_the_tool_and_reports(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        ["run", "--issue", "3", "--repo", "o/r", "--label", "my-x", "--base", "dev"],
        tool_factory=SpyTool,
    )
    assert rc == 0
    (tool,) = SpyTool.instances
    assert tool.issue_number == 3
    assert tool.kwargs["label"] == "my-x"
    assert tool.kwargs["base"] == "dev"
    assert tool.kwargs["github"].repo == "o/r"
    assert isinstance(tool.kwargs["engine"], NoopEngine)
    assert tool.kwargs["ledger"].path == Path(".mythings/ledger.jsonl")
    assert capsys.readouterr().out.strip() == "noop: nothing to change for #1 (issue #1)"


def test_engine_flag_selects_the_claude_backend() -> None:
    main(["run", "--engine", "claude"], tool_factory=SpyTool)
    (tool,) = SpyTool.instances
    assert isinstance(tool.kwargs["engine"], ClaudeCLIEngine)


def test_denied_run_exits_nonzero() -> None:
    SpyTool.result = Result(outcome="denied", detail="policy blocked it", issue=1)
    assert main(["run"], tool_factory=SpyTool) == 1


def test_run_is_the_only_command() -> None:
    with pytest.raises(SystemExit):
        main(["frobnicate"])
