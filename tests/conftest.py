from __future__ import annotations

import pytest

# Shared fakes (FakeGh, ScriptedEngine, make_git_repo, ...) come from the core
# plugin — see my-things-core/docs/CONVENTIONS.md "Shared test fixtures".
# Don't copy fixture code into this file; only domain-specific helpers live here.
pytest_plugins = ("mythings.testing",)


@pytest.fixture(autouse=True)
def _clean_git_env(clean_git_env: None) -> None:
    # Every test in this suite touches real git worktrees; hook-launched
    # pytest (pre-commit) must not leak GIT_* into them.
    pass
