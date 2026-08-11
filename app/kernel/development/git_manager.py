"""Git safety boundary for the Autonomous Development System.

The ``GitManager`` exposes read-only repository inspection used by
development workers to detect which files changed during an execution,
plus a single mutating operation: :meth:`commit`, which stages and
commits the working tree. The commit is deliberately the *only* way the
boundary writes to a repository, and it must be gated by explicit
approval elsewhere — the autonomous loop calls it only after
verification and review both pass, so failing or unreviewed work is
never committed. Pushing and history rewrites remain out of scope.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class GitManager:
    """Read-only operations over a Git working tree."""

    def __init__(self, repository_path: Path) -> None:
        """Store the repository location for read-only Git operations.

        Args:
            repository_path: Root of the repository to inspect.
        """
        self.repository_path = repository_path

    def is_repository(self) -> bool:
        """Return whether ``repository_path`` contains a Git repository.

        The check requires the ``git`` executable and a ``.git`` entry in
        the directory; it never writes to the repository.
        """
        if shutil.which("git") is None:
            return False
        if not self.repository_path.is_dir():
            return False
        return (self.repository_path / ".git").exists()

    def uncommitted_changes(self) -> tuple[Path, ...]:
        """Return the paths currently changed, added, or deleted.

        Paths are parsed from ``git status --porcelain=v1`` and are
        relative to ``repository_path``. Renames resolve to the new path.
        Non-repositories return an empty tuple.

        Returns:
            Changed paths in stable command order.
        """
        if not self.is_repository():
            return ()

        completed = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=self.repository_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return ()

        changed: list[Path] = []
        for line in completed.stdout.splitlines():
            path = self._parse_porcelain_line(line)
            if path is not None:
                changed.append(path)
        return tuple(changed)

    def changed_since(
        self,
        before: tuple[Path, ...],
        after: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        """Return paths present in ``after`` but not in ``before``.

        This is the delta produced by one worker execution: everything
        that appeared while the worker was running.

        Returns:
            Newly changed paths in ``after`` order.
        """
        before_set = set(before)
        return tuple(path for path in after if path not in before_set)

    def commit(self, message: str) -> str:
        """Stage all changes and create a commit, returning its hash.

        This is the only mutating operation on the boundary. It stages
        the full working tree (``git add -A``) and creates a commit with
        ``message``, then resolves and returns the new ``HEAD`` hash.

        Args:
            message: Commit message.

        Returns:
            The new commit's full hash.

        Raises:
            RuntimeError: If the directory is not a repository, staging
                fails, the commit fails, or HEAD cannot be resolved.
        """
        if not self.is_repository():
            raise RuntimeError("not a git repository")

        staged = subprocess.run(
            ["git", "add", "-A"],
            cwd=self.repository_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if staged.returncode != 0:
            detail = (staged.stderr or staged.stdout).strip()
            raise RuntimeError(f"git add failed: {detail}")

        committed = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=self.repository_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if committed.returncode != 0:
            detail = (committed.stderr or committed.stdout).strip()
            raise RuntimeError(f"git commit failed: {detail}")

        resolved = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repository_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if resolved.returncode != 0:
            raise RuntimeError("could not resolve HEAD after commit")
        return resolved.stdout.strip()

    @staticmethod
    def _parse_porcelain_line(line: str) -> Path | None:
        """Extract a repository-relative path from one porcelain line.

        Porcelain v1 lines look like ``XY path`` where ``XY`` is the
        two-character status; renames appear as ``R  old -> new``. Only
        the new path is returned for renames.
        """
        if len(line) < 4:
            return None
        raw = line[3:].strip()
        if not raw:
            return None
        if " -> " in raw:
            raw = raw.split(" -> ", maxsplit=1)[1]
        return Path(raw)
