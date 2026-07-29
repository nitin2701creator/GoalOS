"""Coordinator for deterministic GoalOS repository analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.developer.architecture import ArchitectureAnalyzer, ArchitectureSummary
from app.developer.context import DeveloperContext
from app.developer.feature_request import FeatureRequest
from app.developer.implementation_plan import ImplementationPlan
from app.developer.implementation_planner import ImplementationPlanner
from app.developer.repository_reader import RepositoryReader


class DeveloperAgent:
    """Loads repository context and produces a lightweight architecture summary."""

    def __init__(self, repository_root: str | Path) -> None:
        """Initialize the agent and its analysis collaborators.

        Args:
            repository_root: Directory containing the repository to analyze.
        """

        self.context = DeveloperContext(repository_root)
        self.repository_reader = RepositoryReader(self.context.repository_root)
        self.architecture_analyzer = ArchitectureAnalyzer()
        self.implementation_planner = ImplementationPlanner()

    def load_repository(self) -> dict[str, Any]:
        """Discover source and documentation files and store project metadata."""

        metadata = {
            "repository_root": str(self.context.repository_root),
            "python_module_count": len(self.repository_reader.python_modules()),
            "documentation_file_count": len(
                self.repository_reader.documentation_files()
            ),
        }
        self.context.set_project_metadata(metadata)
        return metadata

    def analyse_repository(self) -> ArchitectureSummary:
        """Analyze repository layers and retain the resulting architecture context."""

        if not self.context.project_metadata():
            self.load_repository()
        architecture = self.architecture_analyzer.analyze(self.repository_reader)
        self.context.set_architecture(architecture)
        return architecture

    def summary(self) -> ArchitectureSummary:
        """Return the repository architecture summary.

        Raises:
            RuntimeError: If repository analysis has not yet been performed.
        """

        architecture = self.context.architecture()
        if architecture is None:
            raise RuntimeError("Repository analysis has not been run")
        return architecture

    def plan_feature(self, request: FeatureRequest) -> ImplementationPlan:
        """Create a code-free implementation plan for a requested feature."""

        architecture = self.context.architecture() or self.analyse_repository()
        return self.implementation_planner.plan(
            request,
            self.repository_reader,
            architecture,
        )
