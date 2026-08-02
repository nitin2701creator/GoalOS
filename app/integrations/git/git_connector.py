"""Readiness checks for the local Git command-line client."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Sequence

from app.integrations.base_connector import BaseConnector


class GitConnector(BaseConnector):
    """Connector that verifies local Git repository availability."""

    name = "git"

    def __init__(self, cwd: str | Path | None = None) -> None:
        self.cwd = cwd

    def connect(self) -> None:
        """Verify that the working directory belongs to a Git repository."""

        if not self._is_git_repository():
            raise RuntimeError("current directory is not inside a Git repository")

    def disconnect(self) -> None:
        """Disconnecting from the local Git executable requires no action."""

    def status(self) -> dict[str, object]:
        """Return the working tree status as a structured command result."""

        return self._run_git(["status", "--short"])

    def current_branch(self) -> dict[str, object]:
        """Return the current branch as a structured command result."""

        result = self._run_git(["branch", "--show-current"])
        if result["success"]:
            result["branch"] = str(result["stdout"]).strip()
        return result

    def diff(self) -> dict[str, object]:
        """Return the unstaged diff as a structured command result."""

        return self._run_git(["diff"])

    def add(self, paths: str | Path | Sequence[str | Path]) -> dict[str, object]:
        """Stage paths and return the Git command result without printing."""

        if isinstance(paths, (str, Path)):
            path_arguments = [str(paths)]
        else:
            path_arguments = [str(path) for path in paths]
        if not path_arguments:
            return self._failure("at least one path is required")
        return self._run_git(["add", "--", *path_arguments])

    def commit(self, message: str) -> dict[str, object]:
        """Create a commit and return the Git command result without printing."""

        if not isinstance(message, str) or not message.strip():
            return self._failure("commit message is required")
        return self._run_git(["commit", "-m", message])

    def health(self) -> bool:
        """Return whether Git is available and the directory is a repository."""

        try:
            git_version = subprocess.run(
                ["git", "--version"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return False

        return git_version.returncode == 0 and self._is_git_repository()

    def _is_git_repository(self) -> bool:
        """Check repository membership without modifying the working tree."""

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return False

        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    def _run_git(self, arguments: Sequence[str]) -> dict[str, object]:
        """Execute a Git command and convert failures into structured results."""

        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            return self._failure(str(error))

        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    @staticmethod
    def _failure(message: str) -> dict[str, object]:
        """Create the shared result shape used for local command failures."""

        return {"success": False, "returncode": None, "stdout": "", "stderr": message}
