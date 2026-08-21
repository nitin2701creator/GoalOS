"""Tests for the GoalOS social media capability layer.

Proves the 16 social capabilities are registered with honest Not Configured
availability, that publishing requires PUBLISH_SOCIAL permission and an
approved workflow context, and that workflow execution never fabricates a
success when the provider is unconfigured. No provider credentials or
external calls exist anywhere in this layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.capability_definitions import (
    BUILTIN_CAPABILITIES,
    CapabilityProviderType,
)
from app.agents.permissions import Permission
from app.db.base import Base
from app.db.models.goal import Goal
from app.db.models.project import Project
from app.db.models.workflow import Workflow
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.social import SocialConnector
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.services.capability_service import CapabilityService
from app.services.execution_runtime import ExecutionRuntimeService
from app.services.workflow_service import WorkflowService

SOCIAL_NAMES = [
    f"social_{provider}_{action}"
    for provider in ("meta", "linkedin", "x", "reddit")
    for action in ("create_post", "publish_post", "get_post")
] + [
    "social_meta_get_insights",
    *(f"social_{provider}_get_analytics" for provider in ("linkedin", "x", "reddit")),
]

PUBLISH_NAMES = [
    f"social_{provider}_{action}"
    for provider in ("meta", "linkedin", "x", "reddit")
    for action in ("create_post", "publish_post")
]


def test_all_social_capabilities_are_registered() -> None:
    for name in SOCIAL_NAMES:
        definition = BUILTIN_CAPABILITIES.get(name)
        assert definition is not None, f"missing social capability {name}"
        assert definition.provider == "social"
        assert definition.provider_type is CapabilityProviderType.INTEGRATION
    # Exactly 16 social capabilities are registered.
    social = {name for name in BUILTIN_CAPABILITIES if name.startswith("social_")}
    assert len(social) == 16


def test_publish_capabilities_require_publish_permission_and_approval() -> None:
    for name in PUBLISH_NAMES:
        definition = BUILTIN_CAPABILITIES[name]
        assert Permission.PUBLISH_SOCIAL in definition.required_permissions
        assert definition.requires_approval is True
    # Read-only capabilities only need READ_SOCIAL and no approval gate.
    for name in (
        "social_meta_get_post",
        "social_meta_get_insights",
        "social_linkedin_get_analytics",
        "social_x_get_post",
        "social_reddit_get_analytics",
    ):
        definition = BUILTIN_CAPABILITIES[name]
        assert Permission.READ_SOCIAL in definition.required_permissions
        assert definition.requires_approval is False


def test_social_connector_reports_not_configured() -> None:
    connector = SocialConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    assert not connector.is_configured
    for capability in ("social.meta.publish_post", "social.linkedin.get_post"):
        available, reason = connector.capability_available(capability)
        assert not available
        assert ("not configured" in reason or "not registered" in reason)
    # Capability permission contract is declared even though nothing runs.
    assert connector.CAPABILITY_PERMISSIONS["social.meta.publish_post"] is Permission.PUBLISH_SOCIAL
    assert connector.CAPABILITY_PERMISSIONS["social.meta.get_insights"] is Permission.READ_SOCIAL


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'social.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


def _service(session: Session) -> CapabilityService:
    registry = ConnectorRegistry()
    registry.register(SocialConnector())
    service = CapabilityService(CapabilityRepository(session), integration_registry=registry)
    service.ensure_seeded()
    return service


def test_social_capability_resolves_unavailable_honestly(session_factory) -> None:
    session = session_factory()
    try:
        service = _service(session)
        resolution = service.resolve("social_meta_publish_post", {Permission.PUBLISH_SOCIAL})
        assert resolution.exists is True
        assert resolution.available is False
        assert "INTEGRATION_NOT_CONFIGURED" in (resolution.reason or "")
    finally:
        session.close()


def test_social_publish_execution_reports_not_configured(session_factory) -> None:
    """Provider-not-configured is the real blocker; it is reported, never faked."""
    session = session_factory()
    try:
        service = _service(session)
        runtime = ExecutionRuntimeService(RuntimeExecutionRepository(session), service)
        result = runtime.execute(
            "social_meta_publish_post",
            {"content": "hello world"},
            {Permission.PUBLISH_SOCIAL},
        )
        assert result.status.value == "failed"
        assert result.error_code == "INTEGRATION_NOT_CONFIGURED"
        assert "INTEGRATION_NOT_CONFIGURED" in (result.error or "")
    finally:
        session.close()


def test_social_publish_workflow_never_claims_fake_success(session_factory) -> None:
    """An approved workflow with a publish step fails honestly when unconfigured."""
    session = session_factory()
    try:
        goal = Goal(title="Social", description="d", executive_owner="CMO", department="Marketing", priority="High")
        session.add(goal)
        session.commit()
        session.refresh(goal)
        project = Project(goal_id=goal.id, title="p", description="d", owner="o", department="Marketing", priority="High")
        session.add(project)
        session.commit()
        session.refresh(project)
        workflow = Workflow(project_id=project.id, name="Social workflow")
        session.add(workflow)
        session.commit()
        session.refresh(workflow)

        service = _service(session)
        workflow_service = WorkflowService(WorkflowRepository(session), ExecutionRepository(session))
        workflow_service.approve(
            workflow.id,
            requirement="Post our product update to Instagram",
            capabilities=("social_meta_publish_post",),
            resolved_capabilities=["social_meta_publish_post"],
            capability_service=service,
        )
        runtime = ExecutionRuntimeService(
            RuntimeExecutionRepository(session),
            service,
            workflow_repository=WorkflowRepository(session),
        )
        run = runtime.run_workflow(
            workflow.id,
            capabilities=("social_meta_publish_post",),
            permissions={Permission.PUBLISH_SOCIAL},
        )
        assert run.workflow.status == "Failed"
        assert run.executions[0].status.value == "blocked"
        assert run.executions[0].error_code == "INTEGRATION_NOT_CONFIGURED"
        error_msg = (run.workflow.error_message or "").casefold()
        assert "not configured" in error_msg or "not registered" in error_msg
    finally:
        session.close()
