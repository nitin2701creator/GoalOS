"""Autonomous-loop tests driven by the coding executors.

The production acceptance path uses the native GoalOS executor with a
deterministic provider while Aider is absent from PATH: the loop must
inspect the repository, actually modify files, run real pytest
subprocesses, review and verify the real changes, and create a real git
commit — all without any external coding CLI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.kernel.development.autonomous import AutonomousLoop, AutonomousState
from app.kernel.development.executors import (
    AiderCodingExecutor,
    NativeGoalOSCodingExecutor,
)
from app.kernel.development.git_manager import GitManager
from app.kernel.development.worker import MockWorker
from tests.kernel.development.helpers import (
    DeterministicEditProvider,
    calculator_plan,
    make_calculator_repo,
)

OBJECTIVE = "Make calculator.add return the sum of its arguments."


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository with a stub calculator and a failing test."""
    return make_calculator_repo(tmp_path / "repo")


@pytest.fixture
def no_aider(monkeypatch: pytest.MonkeyPatch):
    """Remove Aider from PATH while keeping git on PATH."""
    import app.kernel.development.worker as worker_module

    real_which = worker_module.shutil.which
    monkeypatch.setattr(
        worker_module.shutil,
        "which",
        lambda name: None if name == "aider" else real_which(name),
    )


def _loop(repo: Path, executor, **kwargs) -> AutonomousLoop:
    """Build a loop wired to the real repository and an executor."""
    return AutonomousLoop(
        worker=MockWorker(),
        executor=executor,
        git_manager=GitManager(repo),
        repository=repo,
        **kwargs,
    )


def _git(repo: Path, *args: str) -> str:
    """Run a read-only git command and return its trimmed stdout."""
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def test_native_executor_full_autonomous_lifecycle_without_aider(
    repo: Path, no_aider
) -> None:
    """Production acceptance: Aider absent, native executor completes end to end."""
    provider = DeterministicEditProvider([calculator_plan()])
    executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

    record = _loop(repo, executor).run(OBJECTIVE)

    # Inspection happened: the provider saw repository context in its prompt.
    assert provider.requests
    assert "Repository context" in provider.requests[0]

    # The executor really modified the file.
    assert "return a + b" in (repo / "calculator.py").read_text()

    # Tests really ran and passed.
    assert record.state is AutonomousState.COMPLETED
    assert record.attempts == 1
    assert len(record.test_runs) == 1
    assert record.test_runs[0].passed

    # Reviewer and verifier ran against the real changes.
    assert record.review_results[0].passed
    assert record.final_verification is not None
    assert record.final_verification.passed

    # A real commit was created and the tree is clean.
    assert record.commit_hash is not None
    assert _git(repo, "log", "-1", "--format=%s") == "ADS: " + OBJECTIVE
    assert _git(repo, "status", "--porcelain") == ""


def test_native_executor_repairs_test_failures(repo: Path, no_aider) -> None:
    """A broken first plan fails tests; feedback drives a corrected plan."""
    provider = DeterministicEditProvider([calculator_plan(broken=True), calculator_plan()])
    executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

    record = _loop(repo, executor).run(OBJECTIVE)

    assert record.state is AutonomousState.COMPLETED
    assert record.attempts == 2
    assert [run.passed for run in record.test_runs] == [False, True]
    assert any("tests failed" in error for error in record.errors)
    # The repair prompt carried the failing test feedback to the provider.
    assert "tests failed" in provider.requests[1]
    assert record.commit_hash is not None


def test_native_executor_fixes_review_finding(repo: Path, no_aider) -> None:
    """An out-of-scope change passes tests, fails review, then gets fixed."""
    provider = DeterministicEditProvider(
        [calculator_plan(scratch=True), calculator_plan(delete_scratch=True)]
    )
    executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

    record = _loop(repo, executor).run(OBJECTIVE)

    assert record.state is AutonomousState.COMPLETED
    assert record.attempts == 2
    assert not record.review_results[0].passed
    assert any(
        "outside the declared scope" in finding
        for finding in record.review_results[0].findings
    )
    assert record.review_results[1].passed
    assert "Review findings" in provider.requests[1]
    assert not (repo / "scratch.py").exists()
    assert record.commit_hash is not None
    assert "scratch.py" not in _git(repo, "ls-files")


def test_native_executor_retry_limit_fails_and_never_commits(
    repo: Path, no_aider
) -> None:
    """An unfixable plan terminates at the attempt limit with no commit."""
    provider = DeterministicEditProvider([calculator_plan(broken=True)])
    executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

    record = _loop(repo, executor, max_attempts=2).run(OBJECTIVE)

    assert record.state is AutonomousState.FAILED
    assert record.attempts == 2
    assert all(not run.passed for run in record.test_runs)
    assert any("maximum attempts reached" in error for error in record.errors)
    assert record.commit_hash is None
    assert _git(repo, "log", "--format=%s") == "initial"


def test_native_executor_unavailable_provider_fails_run(
    repo: Path, no_aider
) -> None:
    """An unhealthy provider makes the executor unavailable and fails the run."""
    provider = DeterministicEditProvider([calculator_plan()], health=False)
    executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

    record = _loop(repo, executor).run(OBJECTIVE)

    assert record.state is AutonomousState.FAILED
    assert any("executor is unavailable" in error for error in record.errors)
    assert record.commit_hash is None
    # Nothing was implemented.
    assert "return None" in (repo / "calculator.py").read_text()


def test_aider_executor_completes_when_available(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With Aider available, the Aider adapter drives the loop to completion."""
    import app.kernel.development.worker as worker_module

    real_which = worker_module.shutil.which
    real_run = subprocess.run
    monkeypatch.setattr(
        worker_module.shutil,
        "which",
        lambda name: "/usr/bin/aider" if name == "aider" else real_which(name),
    )

    def fake_aider(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command and command[0] == "aider":
            cwd = Path(str(kwargs.get("cwd") or "."))
            (cwd / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
            return subprocess.CompletedProcess(command, 0, "applied", "")
        return real_run(command, **kwargs)

    monkeypatch.setattr(worker_module.subprocess, "run", fake_aider)

    executor = AiderCodingExecutor(repository=repo)
    record = _loop(repo, executor).run(OBJECTIVE)

    assert record.state is AutonomousState.COMPLETED
    assert record.attempts == 1
    assert record.test_runs[0].passed
    assert record.commit_hash is not None
    assert "return a + b" in (repo / "calculator.py").read_text()
    assert _git(repo, "status", "--porcelain") == ""
