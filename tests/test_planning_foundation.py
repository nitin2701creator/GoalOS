from __future__ import annotations

from types import MappingProxyType

import pytest

from app.planning.foundation import PlanningArtifactType, PlanningFoundation


def test_normalize_input_trims_values_and_removes_blank_items() -> None:
    foundation = PlanningFoundation()

    planning_input = foundation.normalize_input(
        vision="  Scale business automation  ",
        mission="  Build deterministic systems  ",
        business_goals=["  Increase throughput  ", "", " Improve transparency "],
        constraints=["  No external calls  ", " "],
    )

    assert planning_input.vision == "Scale business automation"
    assert planning_input.mission == "Build deterministic systems"
    assert planning_input.business_goals == ("Increase throughput", "Improve transparency")
    assert planning_input.constraints == ("No external calls",)


def test_normalize_input_requires_business_goals() -> None:
    foundation = PlanningFoundation()

    with pytest.raises(ValueError, match="At least one business goal is required"):
        foundation.normalize_input(
            vision="Scale business automation",
            mission="Build deterministic systems",
            business_goals=[" "],
        )


def test_artifact_id_is_deterministic_by_type_and_source_key() -> None:
    foundation = PlanningFoundation()

    first_id = foundation.artifact_id(PlanningArtifactType.PROJECT, "objective-1")
    second_id = foundation.artifact_id(PlanningArtifactType.PROJECT, "objective-1")
    different_type_id = foundation.artifact_id(PlanningArtifactType.TASK, "objective-1")

    assert first_id == second_id
    assert first_id != different_type_id


def test_create_artifact_returns_immutable_payload() -> None:
    foundation = PlanningFoundation()

    artifact = foundation.create_artifact(
        artifact_type=PlanningArtifactType.AGENT_REQUIREMENT,
        source_key="goal-1",
        title="  Revenue Operations Agent  ",
        payload={"role": "Planning"},
    )

    assert artifact.title == "Revenue Operations Agent"
    assert artifact.payload == {"role": "Planning"}
    assert isinstance(artifact.payload, MappingProxyType)
