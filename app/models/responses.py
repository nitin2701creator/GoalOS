"""
GoalOS response models.

Shared API response schemas.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., examples=["healthy"])


class SystemInfoResponse(BaseModel):
    """System information response."""

    application: str
    environment: str
    api_version: str
    status: str


class ErrorResponse(BaseModel):
    """Standard API error response."""

    error: str
    message: str
