"""Architecture discovery for the GoalOS Developer Agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.developer.repository_reader import RepositoryReader


@dataclass(frozen=True, slots=True)
class ArchitectureSummary:
    """Structured inventory of the principal repository layers."""

    repository_root: Path
    python_modules: tuple[Path, ...]
    documentation_files: tuple[Path, ...]
    models: tuple[Path, ...]
    schemas: tuple[Path, ...]
    services: tuple[Path, ...]
    repositories: tuple[Path, ...]
    api_routers: tuple[Path, ...]
    tests: tuple[Path, ...]

    def counts(self) -> dict[str, int]:
        """Return file counts for each discovered architectural area."""

        return {
            "python_modules": len(self.python_modules),
            "documentation_files": len(self.documentation_files),
            "models": len(self.models),
            "schemas": len(self.schemas),
            "services": len(self.services),
            "repositories": len(self.repositories),
            "api_routers": len(self.api_routers),
            "tests": len(self.tests),
        }


class ArchitectureAnalyzer:
    """Classifies repository modules into the layers used by GoalOS."""

    def analyze(self, reader: RepositoryReader) -> ArchitectureSummary:
        """Inspect a repository and return its architectural inventory."""

        modules = reader.python_modules()
        return ArchitectureSummary(
            repository_root=reader.repository_root,
            python_modules=modules,
            documentation_files=reader.documentation_files(),
            models=self._in_directory(modules, reader, "app", "db", "models"),
            schemas=self._in_directory(modules, reader, "app", "schemas"),
            services=self._in_directory(modules, reader, "app", "services"),
            repositories=self._in_directory(modules, reader, "app", "repositories"),
            api_routers=self._in_directory(modules, reader, "app", "api"),
            tests=self._in_directory(modules, reader, "tests"),
        )

    def analyse(self, reader: RepositoryReader) -> ArchitectureSummary:
        """Analyze a repository using British spelling compatibility."""

        return self.analyze(reader)

    @staticmethod
    def _in_directory(
        modules: tuple[Path, ...], reader: RepositoryReader, *directory: str
    ) -> tuple[Path, ...]:
        """Return modules located beneath a repository-relative directory."""

        prefix = Path(*directory)
        return tuple(
            path
            for path in modules
            if reader.relative_path(path).is_relative_to(prefix)
        )
