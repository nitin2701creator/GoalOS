"""Tests for the autonomous development loop.

The loop is exercised against a real temporary git repository: the
ScriptedWorker performs real file changes, the test runner executes real
``python -m pytest`` subprocesses, and the GitManager creates real
commits — only the implementation itself is deterministic.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.kernel.development.autonomous import AutonomousLoop, AutonomousState
from app.kernel.development.git_manager import GitManager
from app.kernel.development.worker import MockWorker, WorkerResult
from tests.kernel.development.helpers import (
    ScriptedWorker,
    make_calculator_repo,
    write_broken_calculator,
    write_calculator,
    write_calculator_and_remove_scratch,
    write_calculator_and_scratch,
)

OBJECTIVE = "Make calculator.add return the sum of its arguments."


class CrashingWorker(MockWorker):
    """Worker that always crashes, simulating a broken implementation CLI."""

    def execute(self, prompt: str) -> WorkerResult:
        raise RuntimeError("worker exploded")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository with a stub calculator and a failing test."""
    return make_calculator_repo(tmp_path / "repo")


def _loop(repo: Path, worker, **kwargs) -> AutonomousLoop:
    """Build a loop wired to the real repository boundary."""
    return AutonomousLoop(
        worker=worker,
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


def test_successful_autonomous_implementation_and_commit(repo: Path) -> None:
    """A clean implementation is tested, reviewed, and committed."""
    worker = ScriptedWorker(repo, [write_calculator])

    record = _loop(repo, worker).run(OBJECTIVE)

    assert record.state is AutonomousState.COMPLETED
    assert record.attempts == 1
    assert len(record.test_runs) == 1
    assert record.test_runs[0].passed
    assert record.review_results[0].passed
    assert record.final_verification is not None
    assert record.final_verification.passed
    assert record.commit_hash is not None

    # The implementation really changed the file and the commit is real.
    assert "return a + b" in (repo / "calculator.py").read_text()
    assert _git(repo, "log", "-1", "--format=%s") == "ADS: " + OBJECTIVE
    assert _git(repo, "status", "--porcelain") == ""


def test_implementation_requiring_test_fix_iteration(repo: Path) -> None:
    """A failing first attempt triggers a repair cycle that ends in success."""
    worker = ScriptedWorker(repo, [write_broken_calculator, write_calculator])

    record = _loop(repo, worker).run(OBJECTIVE)

    assert record.state is AutonomousState.COMPLETED
    assert record.attempts == 2
    assert [run.passed for run in record.test_runs] == [False, True]
    assert any("tests failed" in error for error in record.errors)
    assert record.commit_hash is not None
    assert "return a + b" in (repo / "calculator.py").read_text()


def test_reviewer_finding_requires_another_fix(repo: Path) -> None:
    """An out-of-scope change passes tests but fails review, then gets fixed."""
    worker = ScriptedWorker(
        repo,
        [write_calculator_and_scratch, write_calculator_and_remove_scratch],
    )

    record = _loop(repo, worker).run(OBJECTIVE)

    assert record.state is AutonomousState.COMPLETED
    assert record.attempts == 2
    assert not record.review_results[0].passed
    assert any(
        "outside the declared scope" in finding
        for finding in record.review_results[0].findings
    )
    assert record.review_results[1].passed
    assert not (repo / "scratch.py").exists()
    assert record.commit_hash is not None
    # The committed tree contains only the in-scope change.
    assert "scratch.py" not in _git(repo, "ls-files")


def test_failed_task_reaches_failed_state(repo: Path) -> None:
    """A crashing worker fails the run and never commits."""
    worker = CrashingWorker()

    record = _loop(repo, worker).run(OBJECTIVE)

    assert record.state is AutonomousState.FAILED
    assert any("worker crashed" in error for error in record.errors)
    assert record.commit_hash is None


def test_retry_limit_bounds_autonomous_repairs(repo: Path) -> None:
    """An unfixable test failure terminates at the hard attempt limit."""
    worker = ScriptedWorker(repo, [write_broken_calculator])

    record = _loop(repo, worker, max_attempts=2).run(OBJECTIVE)

    assert record.state is AutonomousState.FAILED
    assert record.attempts == 2
    assert len(record.test_runs) == 2
    assert all(not run.passed for run in record.test_runs)
    assert any("maximum attempts reached" in error for error in record.errors)
    assert record.commit_hash is None


def test_no_commit_when_verification_fails(repo: Path) -> None:
    """A failed run preserves the repository's committed state."""
    worker = ScriptedWorker(repo, [write_broken_calculator])

    record = _loop(repo, worker, max_attempts=2).run(OBJECTIVE)

    assert record.state is AutonomousState.FAILED
    assert record.commit_hash is None
    # The original commit is untouched; the broken change stays uncommitted.
    assert _git(repo, "log", "--format=%s") == "initial"
    assert "calculator.py" in _git(repo, "status", "--porcelain")


def test_state_transitions_are_reported_in_order(repo: Path) -> None:
    """Every persisted state transition is reported exactly once, in order."""
    worker = ScriptedWorker(repo, [write_calculator])
    states: list[AutonomousState] = []

    loop = AutonomousLoop(
        worker=worker,
        git_manager=GitManager(repo),
        repository=repo,
        on_state=lambda state, record: states.append(state),
    )
    loop.run(OBJECTIVE)

    assert states == [
        AutonomousState.PLANNING,
        AutonomousState.IMPLEMENTING,
        AutonomousState.TESTING,
        AutonomousState.REVIEWING,
        AutonomousState.COMMITTING,
        AutonomousState.COMPLETED,
    ]


def test_repository_inspection_scopes_api_objective(repo: Path) -> None:
    """An API objective targets the API layer instead of the whole repo."""
    api_dir = repo / "app" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "health.py").write_text("def ping():\n    return 'pong'\n")

    from app.kernel.development.autonomous import RepositoryInspector

    inspection = RepositoryInspector(repo).inspect(
        "Add a health-check endpoint to the API."
    )

    assert any(path.as_posix().startswith("app/api/") for path in inspection.files)
    assert "api" in inspection.layers
    assert all(
        path.as_posix().startswith("app/api/") or "test" in path.as_posix()
        for path in inspection.files
    )
    assert "Plan for" in inspection.summary


def test_loop_rejects_blank_objective(repo: Path) -> None:
    """A blank objective is rejected before any work happens."""
    with pytest.raises(ValueError, match="must not be empty"):
        _loop(repo, ScriptedWorker(repo, [write_calculator])).run("   ")
