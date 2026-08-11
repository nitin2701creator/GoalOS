"""Tests for the read-only Git safety boundary of the ADS kernel."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.kernel.development.git_manager import GitManager


def _run_git(repository: Path, *args: str) -> None:
    """Run a read-only-free setup Git command inside a repository."""
    subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A clean Git repository with one committed file."""
    _run_git(tmp_path, "init", "-q", "-b", "main")
    _run_git(tmp_path, "config", "user.email", "ads@goalos.test")
    _run_git(tmp_path, "config", "user.name", "ADS Tests")
    (tmp_path / "tracked.txt").write_text("v1\n")
    _run_git(tmp_path, "add", "tracked.txt")
    _run_git(tmp_path, "commit", "-q", "-m", "initial")
    return tmp_path


def test_is_repository_false_without_git_directory(tmp_path: Path) -> None:
    """Directories without a ``.git`` entry are not repositories."""

    assert GitManager(tmp_path).is_repository() is False


def test_is_repository_true_in_git_repository(repository: Path) -> None:
    """A directory containing ``.git`` is detected as a repository."""

    assert GitManager(repository).is_repository() is True


def test_uncommitted_changes_empty_in_clean_repository(repository: Path) -> None:
    """A clean repository reports no changes."""

    assert GitManager(repository).uncommitted_changes() == ()


def test_uncommitted_changes_reports_modified_and_untracked(repository: Path) -> None:
    """Modified and untracked files appear as repository-relative paths."""

    (repository / "tracked.txt").write_text("v2\n")
    (repository / "new_file.py").write_text("x = 1\n")

    changes = GitManager(repository).uncommitted_changes()

    assert Path("tracked.txt") in changes
    assert Path("new_file.py") in changes


def test_uncommitted_changes_empty_outside_repository(tmp_path: Path) -> None:
    """Non-repositories report no changes without erroring."""

    assert GitManager(tmp_path).uncommitted_changes() == ()


def test_changed_since_reports_only_delta(repository: Path) -> None:
    """The delta between two snapshots contains only new paths."""

    manager = GitManager(repository)
    before = manager.uncommitted_changes()
    (repository / "delta.txt").write_text("new\n")

    delta = manager.changed_since(before, manager.uncommitted_changes())

    assert delta == (Path("delta.txt"),)


def test_parse_porcelain_line_handles_status_prefixes() -> None:
    """Path extraction strips the two-character status and separator."""

    assert GitManager._parse_porcelain_line(" M app/a.py") == Path("app/a.py")
    assert GitManager._parse_porcelain_line("?? new/file.py") == Path("new/file.py")
    assert GitManager._parse_porcelain_line("A  staged.txt") == Path("staged.txt")


def test_parse_porcelain_line_resolves_rename_to_new_path() -> None:
    """Rename lines resolve to the new path only."""

    assert (
        GitManager._parse_porcelain_line("R  old.py -> new.py")
        == Path("new.py")
    )


def test_parse_porcelain_line_ignores_short_lines() -> None:
    """Lines too short to carry a path are ignored."""

    assert GitManager._parse_porcelain_line("") is None
    assert GitManager._parse_porcelain_line(" M") is None
