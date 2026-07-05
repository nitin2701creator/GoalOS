"""
GoalOS API metadata.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiMetadata:
    """Static API metadata."""

    title: str = "GoalOS"
    version: str = "0.1.0"
    description: str = (
        "AI Operating System for Organigram providing APIs for OpenWebUI agents."
    )
    contact_name: str = "Organigram"
    license_name: str = "Proprietary"


metadata = ApiMetadata()
