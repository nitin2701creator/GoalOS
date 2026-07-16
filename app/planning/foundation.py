"""Sprint 6A.0 planning foundation primitives."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class PlanningArtifactType(StrEnum):
    """Supported planning artifact categories."""

    OBJECTIVE = "objective"
    KPI = "kpi"
    PROJECT = "project"
    TASK = "task"
    WORKFLOW = "workflow"
    DEPENDENCY = "dependency"
    EXECUTION = "execution"
    AGENT_REQUIREMENT = "agent_requirement"


@dataclass(frozen=True, slots=True)
class PlanningInput:
    """Normalized input for deterministic planning.

    Attributes:
        vision: Long-term business vision for the planning run.
        mission: Operating mission for the planning run.
        business_goals: Ordered business goals that planning should satisfy.
        constraints: Ordered constraints that limit generated plans.
    """

    vision: str
    mission: str
    business_goals: tuple[str, ...]
    constraints: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class PlanningArtifact:
    """Stable representation of a generated planning artifact.

    Attributes:
        id: Deterministic artifact identifier.
        artifact_type: Category of generated planning artifact.
        title: Human-readable artifact title.
        payload: Immutable artifact data for downstream planning stages.
        created_at: UTC timestamp for this in-memory artifact instance.
    """

    id: uuid.UUID
    artifact_type: PlanningArtifactType
    title: str
    payload: Mapping[str, Any]
    created_at: datetime


class PlanningFoundation:
    """Provides shared Sprint 6A.0 planning normalization and IDs."""

    _namespace = uuid.UUID("b5a09a8a-6a00-4f00-9000-000000000001")

    def normalize_input(
        self,
        vision: str,
        mission: str,
        business_goals: list[str] | tuple[str, ...],
        constraints: list[str] | tuple[str, ...] | None = None,
    ) -> PlanningInput:
        """Normalize raw planning request values.

        Args:
            vision: Long-term business vision.
            mission: Operating mission.
            business_goals: Business goals to plan against.
            constraints: Optional constraints to preserve on the planning input.

        Returns:
            A normalized planning input.

        Raises:
            ValueError: If required text fields or business goals are missing.
        """

        normalized_goals = self._normalize_text_sequence(business_goals)
        if not normalized_goals:
            raise ValueError("At least one business goal is required")

        normalized_vision = self._normalize_required_text(vision, "vision")
        normalized_mission = self._normalize_required_text(mission, "mission")
        normalized_constraints = self._normalize_text_sequence(constraints or ())

        return PlanningInput(
            vision=normalized_vision,
            mission=normalized_mission,
            business_goals=normalized_goals,
            constraints=normalized_constraints,
        )

    def artifact_id(self, artifact_type: PlanningArtifactType, source_key: str) -> uuid.UUID:
        """Create a deterministic artifact identifier.

        Args:
            artifact_type: Planning artifact category.
            source_key: Stable source key for the artifact.

        Returns:
            A deterministic UUID for the artifact and source key.

        Raises:
            ValueError: If the source key is blank.
        """

        normalized_source_key = self._normalize_required_text(source_key, "source_key")
        return uuid.uuid5(self._namespace, f"{artifact_type.value}:{normalized_source_key}")

    def create_artifact(
        self,
        artifact_type: PlanningArtifactType,
        source_key: str,
        title: str,
        payload: Mapping[str, Any] | None = None,
    ) -> PlanningArtifact:
        """Create an immutable planning artifact.

        Args:
            artifact_type: Planning artifact category.
            source_key: Stable source key for deterministic ID generation.
            title: Human-readable artifact title.
            payload: Optional structured artifact payload.

        Returns:
            A planning artifact with deterministic ID and immutable payload.

        Raises:
            ValueError: If the title or source key is blank.
        """

        normalized_title = self._normalize_required_text(title, "title")
        artifact_payload: Mapping[str, Any] = MappingProxyType(dict(payload or {}))
        return PlanningArtifact(
            id=self.artifact_id(artifact_type, source_key),
            artifact_type=artifact_type,
            title=normalized_title,
            payload=artifact_payload,
            created_at=datetime.now(timezone.utc),
        )

    def _normalize_required_text(self, value: str, field_name: str) -> str:
        """Normalize a required string value."""

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"{field_name} is required")
        return normalized_value

    def _normalize_text_sequence(self, values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        """Normalize an ordered sequence of text values."""

        return tuple(value.strip() for value in values if value.strip())
