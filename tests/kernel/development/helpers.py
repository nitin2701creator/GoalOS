"""Shared helpers for Autonomous Development System loop tests.

The :class:`ScriptedWorker` and :class:`DeterministicEditProvider` are
deterministic stand-ins for a coding CLI/LLM: each call applies the next
scripted change to a real repository (or returns the next scripted edit
plan), so the loop machinery (subprocess test runs, git commits, state
transitions) runs for real while the implementation itself stays
deterministic.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.kernel.development.worker import DevelopmentWorker, WorkerResult
from app.llm.base_provider import BaseProvider

ChangeScript = Callable[[Path, str], list[Path]]


class ScriptedWorker(DevelopmentWorker):
    """Deterministic worker that applies one scripted change per attempt."""

    def __init__(self, repository: Path, scripts: list[ChangeScript]) -> None:
        """Initialize the worker with an ordered list of change scripts.

        Args:
            repository: Repository the scripts mutate.
            scripts: One script per implementation attempt; when the list
                is exhausted the last script is reused.
        """
        self.repository = repository
        self.scripts = scripts
        self.attempts = 0
        self.prompts: list[str] = []

    def execute(self, prompt: str) -> WorkerResult:
        """Apply the next scripted change and return its worker result."""
        self.prompts.append(prompt)
        index = min(self.attempts, len(self.scripts) - 1)
        changed = self.scripts[index](self.repository, prompt)
        self.attempts += 1
        return WorkerResult(
            success=True,
            summary=f"ScriptedWorker attempt {self.attempts} completed.",
            output=f"ScriptedWorker applied changes on attempt {self.attempts}.",
            modified_files=changed,
        )


def make_calculator_repo(repository: Path) -> Path:
    """Create a git repository with a stub calculator and a failing test."""
    repo = Path(repository)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "calculator.py").write_text("def add(a, b):\n    return None\n")
    (repo / "test_calculator.py").write_text(
        "from calculator import add\n\n"
        "def test_add_returns_sum():\n"
        "    assert add(2, 3) == 5\n"
    )
    _git_init(repo)
    return repo


def write_calculator(repository: Path, prompt: str) -> list[Path]:
    """Write the correct calculator implementation."""
    (repository / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    return [Path("calculator.py")]


def write_broken_calculator(repository: Path, prompt: str) -> list[Path]:
    """Write an implementation that fails the repository's test suite."""
    (repository / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    return [Path("calculator.py")]


def write_calculator_and_scratch(repository: Path, prompt: str) -> list[Path]:
    """Write a correct implementation plus an out-of-scope scratch file."""
    write_calculator(repository, prompt)
    (repository / "scratch.py").write_text("pass\n")
    return [Path("calculator.py"), Path("scratch.py")]


def write_calculator_and_remove_scratch(repository: Path, prompt: str) -> list[Path]:
    """Fix the implementation and remove the out-of-scope scratch file."""
    write_calculator(repository, prompt)
    scratch = repository / "scratch.py"
    if scratch.exists():
        scratch.unlink()
    return [Path("calculator.py")]


class DeterministicEditProvider(BaseProvider):
    """Deterministic provider that returns scripted JSON edit plans.

    Each ``request`` returns the next plan in the list (the last plan is
    reused once exhausted), so the provider can model a first broken
    attempt and a corrected attempt. The response is a real edit plan the
    native executor parses, validates, and applies.
    """

    def __init__(self, plans: list[dict[str, Any]], health: bool = True) -> None:
        """Initialize the provider with an ordered list of edit plans."""
        self._plans = list(plans)
        self._index = 0
        self.health = health
        self.requests: list[str] = []

    def request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Return the next scripted plan as a provider payload."""
        self.requests.append(prompt)
        plan = self._plans[min(self._index, len(self._plans) - 1)]
        self._index += 1
        return {"response": json.dumps(plan)}

    def health_check(self) -> bool:
        """Return whether the provider reports itself healthy."""
        return self.health


def calculator_plan(
    *,
    broken: bool = False,
    scratch: bool = False,
    delete_scratch: bool = False,
) -> dict[str, Any]:
    """Build an edit plan for the calculator fixture."""
    content = (
        "def add(a, b):\n    return a - b\n"
        if broken
        else "def add(a, b):\n    return a + b\n"
    )
    files: list[dict[str, str]] = [{"path": "calculator.py", "content": content}]
    if scratch:
        files.append({"path": "scratch.py", "content": "pass\n"})
    plan: dict[str, Any] = {"files": files}
    if delete_scratch:
        plan["delete"] = ["scratch.py"]
    return plan


def _git_init(repo: Path) -> None:
    """Initialize a git repository with an initial commit and local identity."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "ads@goalos.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "GoalOS ADS"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
