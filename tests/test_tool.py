from __future__ import annotations

import json
from pathlib import Path

import pytest
from mythings.engine import EngineRequest, EngineResult, NoopEngine
from mythings.github import GitHub
from mythings.ledger import Ledger, LedgerEntry
from mythings.policy import Action, Decision, PolicyResult
from mythings.testing import FakeGh, GitRepo, make_git_repo

from myequations.extract import EquationRegion
from myequations.tool import LEDGER_KIND, TOOL, Tool, _run_git


def gh_for(issues: list[dict] | None = None) -> FakeGh:
    return FakeGh(
        {
            ("issue", "list"): json.dumps(issues or []),
            ("pr", "create"): "https://github.com/o/r/pull/7\n",
        }
    )


def issue_obj(number: int = 1, body: str = "eq-source:/tmp/does-not-exist.pdf") -> dict:
    return {
        "number": number,
        "title": "extract equations",
        "body": body,
        "url": f"https://github.com/o/r/issues/{number}",
        "labels": [{"name": "my-equations"}],
    }


@pytest.fixture()
def clone(tmp_path: Path) -> GitRepo:
    return make_git_repo(tmp_path, files={"README.md": "seed\n"})


def make_tool(
    clone: GitRepo,
    tmp_path: Path,
    runner: FakeGh,
    *,
    extractor,
    engine=None,
    real_git: bool = False,
    **kwargs,
):
    git_calls: list[tuple[Path, list[str]]] = []

    def git(tree: Path, argv: list[str]) -> None:
        git_calls.append((tree, argv))
        if real_git:
            _run_git(tree, argv)

    tool = Tool(
        repo=clone.path,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        github=GitHub("o/r", runner=runner),
        engine=engine or NoopEngine(),
        git=git,
        extractor=extractor,
        **kwargs,
    )
    return tool, git_calls


def ledger_entries(tmp_path: Path) -> list[LedgerEntry]:
    path = tmp_path / "ledger.jsonl"
    return [LedgerEntry.from_json(line) for line in path.read_text().splitlines()]


def test_no_labeled_issue_is_skipped(clone: GitRepo, tmp_path: Path) -> None:
    runner = gh_for(issues=[])
    tool, _ = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    result = tool.run()
    assert result.outcome == "skipped"
    (entry,) = ledger_entries(tmp_path)
    assert (entry.tool, entry.kind, entry.outcome) == (TOOL, LEDGER_KIND, "skipped")


def test_unknown_issue_number_is_skipped(clone: GitRepo, tmp_path: Path) -> None:
    runner = gh_for(issues=[issue_obj(number=4)])
    tool, _ = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    assert tool.run(issue_number=99).outcome == "skipped"


def test_missing_eq_source_locator_is_a_noop(clone: GitRepo, tmp_path: Path) -> None:
    runner = gh_for(issues=[issue_obj(body="no locator here")])
    tool, git_calls = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    result = tool.run()
    assert result.outcome == "noop"
    assert not git_calls


class _FakeExtractor:
    def __init__(self, regions: list[EquationRegion]) -> None:
        self.regions = regions
        self.paths: list[Path] = []

    def __call__(self, path: Path) -> list[EquationRegion]:
        self.paths.append(path)
        return self.regions


def test_every_region_is_batched_into_one_required_engine_call(
    clone: GitRepo, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    regions = [
        EquationRegion(page=1, bbox=(0, 0, 10, 10), image=b"one", nearby_text="sigma is noise"),
        EquationRegion(page=2, bbox=(0, 0, 10, 10), image=b"two", nearby_text="mu is the mean"),
    ]
    extractor = _FakeExtractor(regions)

    class ScriptedEngine:
        def __init__(self) -> None:
            self.calls = 0
            self.seen: EngineRequest | None = None

        def run(self, request: EngineRequest) -> EngineResult:
            self.calls += 1
            self.seen = request
            return EngineResult(
                text=json.dumps(
                    {
                        "equations": [
                            {
                                "latex": r"\sigma^2 = E[(x-\mu)^2]",
                                "symbols": [{"symbol": "\\sigma", "meaning": "noise std dev"}],
                            },
                            {
                                "latex": r"\mu = E[x]",
                                "symbols": [{"symbol": "\\mu", "meaning": ""}],
                            },
                        ]
                    }
                )
            )

    engine = ScriptedEngine()
    runner = gh_for(issues=[issue_obj(body=f"eq-source:{source}")])
    tool, git_calls = make_tool(
        clone, tmp_path, runner, extractor=extractor, engine=engine, real_git=True
    )
    result = tool.run()

    assert result.outcome == "success"
    assert engine.calls == 1  # exactly one Engine call per run, batched over all regions
    assert engine.seen is not None
    assert engine.seen.images == (b"one", b"two")

    ops = [argv[0] for _, argv in git_calls]
    assert ops == ["checkout", "add", "commit", "push"]
    add_path = git_calls[1][1][1]
    assert add_path == "equations/book"

    index = json.loads(clone.read_committed("my-equations/1", "equations/book/index.json"))
    rows = {row["image"]: row for row in index["equations"]}
    assert rows["p1-1.png"]["latex"] == r"\sigma^2 = E[(x-\mu)^2]"
    assert rows["p1-1.png"]["symbols"] == [{"symbol": "\\sigma", "meaning": "noise std dev"}]
    assert rows["p2-2.png"]["symbols"][0]["meaning"] == ""  # ungrounded symbol, never invented


def test_no_regions_found_is_a_noop(
    clone: GitRepo, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    runner = gh_for(issues=[issue_obj(body=f"eq-source:{source}")])
    tool, git_calls = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    result = tool.run()
    assert result.outcome == "noop"
    assert not git_calls
    (entry,) = [e for e in ledger_entries(tmp_path) if e.outcome == "noop"]
    assert entry.detail == "nothing to change for #1"


def test_nonexistent_source_path_is_a_noop(clone: GitRepo, tmp_path: Path) -> None:
    runner = gh_for(issues=[issue_obj(body="eq-source:/nowhere/nothing.pdf")])
    tool, git_calls = make_tool(clone, tmp_path, runner, extractor=lambda p: [])
    result = tool.run()
    assert result.outcome == "noop"
    assert not git_calls


def test_noop_engine_still_indexes_regions_with_empty_transcription(
    clone: GitRepo, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    regions = [EquationRegion(page=1, bbox=(0, 0, 10, 10), image=b"one", nearby_text="text")]
    extractor = _FakeExtractor(regions)
    runner = gh_for(issues=[issue_obj(body=f"eq-source:{source}")])
    tool, _ = make_tool(
        clone, tmp_path, runner, extractor=extractor, engine=NoopEngine(), real_git=True
    )
    result = tool.run()

    assert result.outcome == "success"
    index = json.loads(clone.read_committed("my-equations/1", "equations/book/index.json"))
    assert index["equations"][0]["latex"] == ""
    assert index["equations"][0]["symbols"] == []


def test_unparsable_engine_reply_degrades_to_empty_transcription(
    clone: GitRepo, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    regions = [EquationRegion(page=1, bbox=(0, 0, 10, 10), image=b"one", nearby_text="text")]
    extractor = _FakeExtractor(regions)

    class GarbageEngine:
        def run(self, request: EngineRequest) -> EngineResult:
            return EngineResult(text="not json")

    runner = gh_for(issues=[issue_obj(body=f"eq-source:{source}")])
    tool, _ = make_tool(
        clone, tmp_path, runner, extractor=extractor, engine=GarbageEngine(), real_git=True
    )
    result = tool.run()

    assert result.outcome == "success"
    index = json.loads(clone.read_committed("my-equations/1", "equations/book/index.json"))
    assert index["equations"][0]["latex"] == ""
    assert index["equations"][0]["symbols"] == []


class AskPolicy:
    def evaluate(self, action: Action) -> PolicyResult:
        return PolicyResult(Decision.ASK, reason="needs a human")


def test_ask_fails_closed_unattended(
    clone: GitRepo,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    source = tmp_path_factory.mktemp("src") / "book.pdf"
    source.write_bytes(b"%PDF fake")
    regions = [EquationRegion(page=1, bbox=(0, 0, 10, 10), image=b"one", nearby_text="text")]
    runner = gh_for(issues=[issue_obj(body=f"eq-source:{source}")])
    tool, git_calls = make_tool(
        clone,
        tmp_path,
        runner,
        extractor=_FakeExtractor(regions),
        engine=NoopEngine(),
        policy=AskPolicy(),
    )
    result = tool.run()
    assert result.outcome == "denied"
    assert not git_calls
    assert not runner.saw("pr", "create")
