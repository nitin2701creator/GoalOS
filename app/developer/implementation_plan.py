"""Pydantic models returned by the implementation planner."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Priority(StrEnum):
    """Relative importance of an implementation step."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Complexity(StrEnum):
    """Estimated implementation effort for a plan or plan step."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImplementationStep(BaseModel):
    """One ordered, code-free implementation activity."""

    model_config = ConfigDict(frozen=True)

    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    files_to_create: tuple[str, ...] = ()
    files_to_modify: tuple[str, ...] = ()
    priority: Priority
    dependencies: tuple[str, ...] = ()
    estimated_complexity: Complexity


class ImplementationPlan(BaseModel):
    """A deterministic, non-executable plan for a requested feature."""

    model_config = ConfigDict(frozen=True)

    feature_name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    repository_root: str = Field(min_length=1)
    architecture_counts: dict[str, int]
    steps: tuple[ImplementationStep, ...] = Field(min_length=1)
    files_to_create: tuple[str, ...] = ()
    files_to_modify: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    estimated_complexity: Complexity

