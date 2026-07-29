from __future__ import annotations

from app.developer import Complexity, DeveloperAgent, FeatureRequest, Priority


def test_plan_feature_analyzes_repository_and_returns_ordered_api_plan() -> None:
    agent = DeveloperAgent(".")

    plan = agent.plan_feature(
        FeatureRequest(
            feature_name="Goal Activity",
            description="Add an API endpoint for persisted goal activity.",
            requirements=("Return a Pydantic response schema.",),
        )
    )

    assert plan.feature_name == "Goal Activity"
    assert plan.architecture_counts["services"] > 0
    assert tuple(step.order for step in plan.steps) == tuple(
        range(1, len(plan.steps) + 1)
    )
    assert "app/services/goal_activity_service.py" in plan.files_to_create
    assert "app/repositories/goal_activity_repository.py" in plan.files_to_create
    assert "app/api/v1/goal_activity.py" in plan.files_to_create
    assert "app/api/router.py" in plan.files_to_modify
    assert plan.steps[-1].priority is Priority.HIGH
    assert plan.estimated_complexity is Complexity.HIGH


def test_plan_feature_respects_constraints_without_generating_code() -> None:
    agent = DeveloperAgent(".")

    plan = agent.plan_feature(
        FeatureRequest(
            name="Developer insight",
            description="Extend Developer Agent repository analysis.",
            constraints=("Do not modify application business logic.",),
        )
    )

    assert plan.feature_name == "Developer insight"
    assert "Do not modify application business logic." in plan.steps[0].description
    assert all("do not generate code" in step.description for step in plan.steps)
    assert "app/developer/developer_insight.py" in plan.files_to_create
