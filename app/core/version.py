"""
GoalOS version information.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VersionInfo:
    """Application version details."""

    name: str = "GoalOS"
    version: str = "0.1.0"
    api_version: str = "v1"
    build: str = "dev"
    author: str = "Organigram"


VERSION = VersionInfo()
