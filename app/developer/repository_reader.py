"""Safe repository file discovery for the Developer Agent."""

from __future__ import annotations

from pathlib import Path


class RepositoryReader:
    """Recursively discovers source and documentation files in a repository."""

    _ignored_directories = frozenset({".git", "__pycache__", ".venv"})

    def __init__(self, repository_root: str | Path) -> None:
        """Create a reader rooted at an existing directory.

        Args:
            repository_root: Repository directory to inspect.

        Raises:
            ValueError: If the directory does not exist.
        """

        root = Path(repository_root).resolve()
        if not root.is_dir():
            raise ValueError(f"Repository root must be a directory: {root}")
        self.repository_root = root

    def python_modules(self) -> tuple[Path, ...]:
        """Return all Python source files outside ignored directories."""

        return self._files_with_suffix(".py")

    def documentation_files(self) -> tuple[Path, ...]:
        """Return Markdown documentation files outside ignored directories."""

        return self._files_with_suffix(".md")

    def relative_path(self, path: Path) -> Path:
        """Return a path relative to the repository root."""

        return path.relative_to(self.repository_root)

    def _files_with_suffix(self, suffix: str) -> tuple[Path, ...]:
        """Discover files with a suffix while excluding generated directories."""

        files = (
            path
            for path in self.repository_root.rglob(f"*{suffix}")
            if path.is_file() and not self._is_ignored(path)
        )
        return tuple(sorted(files))

    def _is_ignored(self, path: Path) -> bool:
        """Return whether a file resides in a directory excluded from inspection."""

        return any(
            part in self._ignored_directories
            for part in path.relative_to(self.repository_root).parts
        )
