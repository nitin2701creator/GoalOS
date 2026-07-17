"""Deterministic implementation planning based on repository architecture."""

from __future__ import annotations

from collections.abc import Iterable

from app.developer.architecture import ArchitectureSummary
from app.developer.feature_request import FeatureRequest
from app.developer.implementation_plan import (
    Complexity,
    ImplementationPlan,
    ImplementationStep,
    Priority,
)
from app.developer.repository_reader import RepositoryReader


class ImplementationPlanner:
    """Creates code-free plans that follow GoalOS layer boundaries."""

    def plan(
        self,
        request: FeatureRequest,
        reader: RepositoryReader,
        architecture: ArchitectureSummary,
    ) -> ImplementationPlan:
        """Create an ordered plan using the repository and its architecture.

        The planner only inventories and recommends files. It never reads mutable
        state, writes files, or generates implementation code.
        """

        feature_slug = self._slug(request.feature_name)
        layers = self._relevant_layers(request, architecture)
        steps = self._build_steps(feature_slug, request, layers)
        files_to_create = self._unique_paths(
            path for step in steps for path in step.files_to_create
        )
        files_to_modify = self._unique_paths(
            path for step in steps for path in step.files_to_modify
        )
        dependencies = self._unique_paths(
            dependency for step in steps for dependency in step.dependencies
        )

        return ImplementationPlan(
            feature_name=request.feature_name,
            summary=(
                f"Plan {request.feature_name} within the existing GoalOS "
                "repository, service, and API boundaries."
            ),
            repository_root=str(reader.repository_root),
            architecture_counts=architecture.counts(),
            steps=steps,
            files_to_create=files_to_create,
            files_to_modify=files_to_modify,
            dependencies=dependencies,
            estimated_complexity=self._complexity(steps),
        )

    @staticmethod
    def _relevant_layers(
        request: FeatureRequest, architecture: ArchitectureSummary
    ) -> tuple[str, ...]:
        """Select existing layers relevant to the request language."""

        text = " ".join(
            (request.feature_name, request.description, *request.requirements)
        ).lower()
        layers = ["service", "test"]
        if any(term in text for term in ("api", "endpoint", "route", "http")):
            layers.extend(("schema", "repository", "api"))
        elif any(term in text for term in ("database", "persist", "storage", "model")):
            layers.extend(("model", "repository", "schema"))
        elif "developer agent" in text or "repository analysis" in text:
            layers.append("developer")

        available = {
            "model": architecture.models,
            "schema": architecture.schemas,
            "service": architecture.services,
            "repository": architecture.repositories,
            "api": architecture.api_routers,
            "test": architecture.tests,
            "developer": architecture.python_modules,
        }
        return tuple(layer for layer in layers if available[layer] or layer == "test")

    def _build_steps(
        self, feature_slug: str, request: FeatureRequest, layers: tuple[str, ...]
    ) -> tuple[ImplementationStep, ...]:
        """Build an ordered implementation sequence for the selected layers."""

        steps: list[ImplementationStep] = []
        if "model" in layers:
            steps.append(self._step(len(steps) + 1, "Define persistence model", feature_slug, "model"))
        if "schema" in layers:
            steps.append(self._step(len(steps) + 1, "Define request and response schemas", feature_slug, "schema"))
        if "repository" in layers:
            steps.append(self._step(len(steps) + 1, "Add repository operations", feature_slug, "repository"))
        if "service" in layers:
            steps.append(self._step(len(steps) + 1, "Add service orchestration", feature_slug, "service"))
        if "developer" in layers:
            steps.append(self._step(len(steps) + 1, "Extend developer planning boundary", feature_slug, "developer"))
        if "api" in layers:
            steps.append(self._step(len(steps) + 1, "Expose API route", feature_slug, "api"))
        steps.append(self._step(len(steps) + 1, "Add focused verification", feature_slug, "test"))

        if request.constraints:
            constraint_text = "; ".join(request.constraints)
            first_step = steps[0]
            steps[0] = first_step.model_copy(
                update={
                    "description": f"{first_step.description} Respect constraints: {constraint_text}."
                }
            )
        return tuple(steps)

    @staticmethod
    def _step(order: int, title: str, slug: str, layer: str) -> ImplementationStep:
        """Create a layer-specific plan step."""

        paths = {
            "model": (f"app/db/models/{slug}.py", "app/db/models/__init__.py"),
            "schema": (f"app/schemas/{slug}.py",),
            "repository": (f"app/repositories/{slug}_repository.py",),
            "service": (f"app/services/{slug}_service.py",),
            "api": (f"app/api/v1/{slug}.py", "app/api/router.py"),
            "developer": (f"app/developer/{slug}.py", "app/developer/__init__.py"),
            "test": (f"tests/test_{slug}.py",),
        }
        dependencies = {
            "model": (),
            "schema": (),
            "repository": ("persistence model",),
            "service": ("repository interface",),
            "api": ("service interface", "Pydantic schemas"),
            "developer": ("repository analysis context",),
            "test": ("planned application interfaces",),
        }
        files = paths[layer]
        create = tuple(path for path in files if path.endswith(".py") and "__init__" not in path and path != "app/api/router.py")
        modify = tuple(path for path in files if path not in create)
        return ImplementationStep(
            order=order,
            title=title,
            description=f"Plan the {layer} changes needed for {slug.replace('_', ' ')}; do not generate code.",
            files_to_create=create,
            files_to_modify=modify,
            priority=Priority.HIGH if layer in {"service", "test"} else Priority.MEDIUM,
            dependencies=dependencies[layer],
            estimated_complexity=Complexity.MEDIUM if layer in {"service", "api", "repository"} else Complexity.LOW,
        )

    @staticmethod
    def _complexity(steps: tuple[ImplementationStep, ...]) -> Complexity:
        """Derive a concise overall estimate from planned work."""

        if len(steps) >= 5:
            return Complexity.HIGH
        if any(step.estimated_complexity is Complexity.MEDIUM for step in steps):
            return Complexity.MEDIUM
        return Complexity.LOW

    @staticmethod
    def _slug(value: str) -> str:
        """Convert a feature name into a repository-safe module name."""

        characters = (character.lower() if character.isalnum() else "_" for character in value)
        return "_".join(part for part in "".join(characters).split("_") if part)

    @staticmethod
    def _unique_paths(values: Iterable[str]) -> tuple[str, ...]:
        """Return values once while retaining their first-seen order."""

        return tuple(dict.fromkeys(values))
