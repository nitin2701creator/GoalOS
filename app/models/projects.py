"""
GoalOS project models.

Defines project entities managed by the Project Engine.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class Project(BaseModel):
    id: str
    name: str
    description: str
    owner: str
    status: ProjectStatus = ProjectStatus.PLANNED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectSummary(BaseModel):
    total_projects: int
    active_projects: int
    blocked_projects: int
    completed_projects: int
