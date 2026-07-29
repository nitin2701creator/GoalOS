"""Context shared by Developer Agent repository-analysis components."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.developer.architecture import ArchitectureSummary


class DeveloperContext:
    """Stores repository details discovered during a developer-agent run.

    The context deliberately holds only repository metadata and analysis results.
    It does not make changes to the repository or execute commands.
    """

    def __init__(self, repository_root: str | Path) -> None:
        """Initialize context for an existing repository root.

        Args:
            repository_root: Directory that contains the repository to inspect.

        Raises:
            ValueError: If the supplied path is not a directory.
        """

        root = Path(repository_root).resolve()
        if not root.is_dir():
            raise ValueError(f"Repository root must be a directory: {root}")

        self._repository_root = root
        self._project_metadata: dict[str, Any] = {}
        self._architecture: ArchitectureSummary | None = None

    @property
    def repository_root(self) -> Path:
        """Return the resolved repository root."""

        return self._repository_root

    def set_project_metadata(self, metadata: Mapping[str, Any]) -> None:
        """Store a defensive copy of project metadata."""

        self._project_metadata = dict(metadata)

    def project_metadata(self) -> dict[str, Any]:
        """Return a copy of the discovered project metadata."""

        return dict(self._project_metadata)

    def set_architecture(self, architecture: ArchitectureSummary) -> None:
        """Store the latest architecture analysis result."""

        self._architecture = architecture

    def architecture(self) -> ArchitectureSummary | None:
        """Return the latest architecture analysis, when available."""

        return self._architecture
