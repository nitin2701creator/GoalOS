"""
CEO planning API schemas.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CEOPlanRequest(BaseModel):
    """Request to generate an executive business plan."""

    goal: str = Field(
        ...,
        min_length=3,
        examples=["Increase Organigram revenue to ₹1 crore/month"],
    )


class CEOPlanResponse(BaseModel):
    """Structured CEO business plan response."""

    goal: str
    executive_owner: str
    priority: str
    timeline: str
    objectives: list[str]
    departments: list[str]
    KPIs: list[str]
    milestones: list[str]
    risks: list[str]
    next_actions: list[str]
