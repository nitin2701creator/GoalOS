"""API schemas for GoalOS skill definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.permissions import Permission


class SkillCreateRequest(BaseModel):
    """Request to create a reusable skill definition."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    instructions: str = ""
    required_tools: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[Permission] = Field(default_factory=list)
    version: str = "1.0"
    enabled: bool = True


class SkillResponse(BaseModel):
    """API representation of a persisted skill definition."""

    id: UUID
    name: str
    description: str
    instructions: str
    required_tools: list[str]
    required_integrations: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[Permission]
    version: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
