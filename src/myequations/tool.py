from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mythings.engine import Engine, EngineRequest, EngineResult
from mythings.github import GitHub, Issue
from mythings.ledger import Ledger
from mythings.policy import Policy
from mythings.tool import BaseToolRunner
from mythings.tool import ToolRunResult as Result

# The per-tool constants. The rename step (scripts/init.py, or the manual grep
# sweep in README.md) rewrites these alongside the CLAUDE.md seams.
TOOL = "myequations"
LEDGER_KIND = "template"  # this tool's own runtime-Ledger kind
BACKLOG_LABEL = "my-equations"  # the GitHub issue label it picks up

# Seam: the system prompt for the single Engine call.
SYSTEM = ""


class Tool(BaseToolRunner):
    # The harness loop, already wired: read one labeled issue → deterministic
    # pre-work → one Engine call → apply inside an isolated Workspace → draft
    # PR, with the side effect gated by Policy and every run ledgered. A new
    # tool overrides the three seam methods (prework/request/apply) and the
    # constants above; the plumbing here should not need to change.

    def __init__(
        self,
        *,
        repo: str | Path = ".",
        ledger: Ledger | None = None,
        github: GitHub | None = None,
        engine: Engine | None = None,
        policy: Policy | None = None,
        base: str = "main",
        label: str = BACKLOG_LABEL,
        git: Callable[[Path, list[str]], None] | None = None,
    ) -> None:
        super().__init__(
            repo=repo,
            ledger=ledger,
            github=github,
            engine=engine,
            policy=policy,
            base=base,
            label=label,
            git=git,
        )

    # -- seams -----------------------------------------------------------

    def prework(self, issue: Issue) -> str:
        # Deterministic pre-work: gather whatever cheap, local context the
        # Engine call needs. No judgment here.
        return issue.body

    def request(self, issue: Issue, context: str) -> EngineRequest:
        # The single Engine call. Keep the prompt narrowly scoped to this
        # tool's one judgment step.
        prompt = f"{issue.title}\n\n{context}" if context else issue.title
        return EngineRequest(prompt=prompt, system=SYSTEM)

    def apply(self, tree: Path, issue: Issue, result: EngineResult) -> str | None:
        # Turn the Engine's reply into a change inside the isolated worktree
        # and return the path (relative to `tree`) to commit — or None for
        # "nothing to do", which ends the run as a safe no-op. The pristine
        # template changes nothing, so `run --engine noop` is a dry run.
        return None

    def run(self, issue_number: int | None = None) -> Result:
        return self.run_issue_workflow(TOOL, LEDGER_KIND, issue_number)

