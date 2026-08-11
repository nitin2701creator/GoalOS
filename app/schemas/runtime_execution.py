"""
API schemas for the GoalOS execution runtime.

The runtime executes ONE capability at a time through a clean executor
interface and persists every attempt: inputs, outputs, errors,
permissions, and timestamps. An unconfigured provider is persisted as a
``failed`` execution carrying the honest ``INTEGRATION_NOT_CONFIGURED``
reason — never a fabricated success.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.permissions import Permission
from app.db.models.runtime_execution import RuntimeExecutionStatus
from app.schemas.workflow import WorkflowResponse


class RuntimeExecuteRequest(BaseModel):
    """Request to execute one capability through the runtime.

    Attributes:
        capability: The registered capability name to execute.
        params: Structured input parameters for the capability.
        permissions: The explicitly granted permissions of the calling
            agent/operator — the runtime never escalates permissions.
        workflow_id: Optional owning workflow; when provided, duplicate
            in-flight executions for the workflow are refused.
        agent_name: Optional executing agent identity for the audit trail.
        metadata: Optional caller-supplied metadata persisted verbatim.
    """

    capability: str = Field(min_length=1, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)
    permissions: list[Permission] = Field(default_factory=list)
    workflow_id: UUID | None = None
    agent_name: str | None = None
    metadata: dict[str, Any] | None = None


class RuntimeExecutionResponse(BaseModel):
    """Persisted outcome of one capability execution."""

    id: UUID
    workflow_id: UUID | None = None
    capability: str
    status: RuntimeExecutionStatus
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    provider: str | None = None
    permissions_required: list[str] = Field(default_factory=list)
    agent_name: str | None = None
    execution_metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RuntimeWorkflowRunRequest(BaseModel):
    """Request to run an approved workflow through the execution runtime.

    The workflow must have been approved (created and prepared through the
    existing ``WorkflowService``) with a requirement. Capabilities default
    to the workflow's persisted plan; permissions default to the
    permissions of the agent the factory resolves/reuses for the
    capability set.
    """

    requirement: str | None = None
    capabilities: list[str] | None = None
    permissions: list[Permission] | None = None
    agent_name: str | None = None


class RuntimeWorkflowRunResponse(BaseModel):
    """Result of a workflow runtime run: the updated workflow plus the
    per-capability runtime execution records."""

    workflow: WorkflowResponse
    executions: list[RuntimeExecutionResponse] = Field(default_factory=list)
