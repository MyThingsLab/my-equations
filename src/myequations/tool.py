from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mythings.engine import Engine, EngineRequest, EngineResult
from mythings.github import GitHub, Issue
from mythings.isolation import Workspace, in_github_actions
from mythings.ledger import Ledger
from mythings.policy import ALLOW, Action, Decision, Policy, PolicyResult

# The per-tool constants. The rename step (scripts/init.py, or the manual grep
# sweep in README.md) rewrites these alongside the CLAUDE.md seams.
TOOL = "myequations"
LEDGER_KIND = "template"  # this tool's own runtime-Ledger kind
BACKLOG_LABEL = "my-equations"  # the GitHub issue label it picks up

# Seam: the system prompt for the single Engine call.
SYSTEM = ""


class _AllowAll:
    # Default Policy for tools whose one side effect is a non-destructive draft
    # PR (my-changelogger's rationale). Swap in a real gate (e.g. myguard.Guard)
    # when the tool's `apply` grows teeth.
    def evaluate(self, action: Action) -> PolicyResult:
        return ALLOW


def _run_git(tree: Path, argv: list[str]) -> None:
    proc = subprocess.run(["git", *argv], cwd=tree, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )


@dataclass(frozen=True)
class Result:
    outcome: str  # success | noop | skipped | denied | failure
    detail: str
    issue: int | None = None
    pr: int | None = None


class Tool:
    # The harness loop, already wired: read one labeled issue → deterministic
    # pre-work → one Engine call → apply inside an isolated Workspace → draft
    # PR, with the side effect gated by Policy and every run ledgered. A new
    # tool overrides the three seam methods (prework/request/apply) and the
    # constants above; the plumbing here should not need to change.

    def __init__(
        self,
        *,
        repo: str | Path = ".",
        ledger: Ledger,
        github: GitHub,
        engine: Engine,
        policy: Policy | None = None,
        base: str = "main",
        label: str = BACKLOG_LABEL,
        git: Callable[[Path, list[str]], None] = _run_git,
    ) -> None:
        self.repo = Path(repo)
        self.ledger = ledger
        self.github = github
        self.engine = engine
        self.policy = policy or _AllowAll()
        self.base = base
        self.label = label
        self._git = git

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

    # -- plumbing --------------------------------------------------------

    def pick_issue(self, number: int | None = None) -> Issue | None:
        issues = self.github.list_issues(labels=[self.label])
        if number is not None:
            return next((i for i in issues if i.number == number), None)
        return min(issues, key=lambda i: i.number) if issues else None

    def run(self, issue_number: int | None = None) -> Result:
        issue = self.pick_issue(issue_number)
        if issue is None:
            detail = f"no open '{self.label}' issue" + (
                f" #{issue_number}" if issue_number is not None else ""
            )
            self.ledger.record(TOOL, LEDGER_KIND, "skipped", detail)
            return Result(outcome="skipped", detail=detail)

        context = self.prework(issue)
        engine_result = self.engine.run(self.request(issue, context))

        with Workspace(self.repo, base_ref=f"origin/{self.base}") as tree:
            relpath = self.apply(tree, issue, engine_result)
            if relpath is None:
                detail = f"nothing to change for #{issue.number}"
                self.ledger.record(TOOL, LEDGER_KIND, "noop", detail, issue=issue.number)
                return Result(outcome="noop", detail=detail, issue=issue.number)

            branch = f"{self.label}/{issue.number}"
            gate = self.policy.evaluate(
                Action(kind="bash", payload={"command": f"gh pr create --head {branch}"})
            )
            if gate.under(unattended=in_github_actions()) is not Decision.ALLOW:
                detail = f"policy blocked the PR for #{issue.number}: {gate.reason or gate.rule}"
                self.ledger.record(TOOL, LEDGER_KIND, "denied", detail, issue=issue.number)
                return Result(outcome="denied", detail=detail, issue=issue.number)

            self._git(tree, ["checkout", "-b", branch])
            self._git(tree, ["add", relpath])
            self._git(tree, ["commit", "-m", f"{TOOL}: {issue.title}"])
            self._git(tree, ["push", "-u", "origin", branch])
            pr = self.github.open_pr(
                title=issue.title,
                body=f"Closes #{issue.number}.",
                base=self.base,
                head=branch,
                draft=True,
            )

        self.ledger.record(
            TOOL,
            LEDGER_KIND,
            "success",
            f"PR #{pr.number} for #{issue.number}",
            issue=issue.number,
            pr=pr.number,
        )
        return Result(
            outcome="success",
            detail=f"opened draft PR #{pr.number}",
            issue=issue.number,
            pr=pr.number,
        )
