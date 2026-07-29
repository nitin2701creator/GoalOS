"""Roadmap access boundary for the Autonomous Development System."""

from __future__ import annotations

from pathlib import Path


class RoadmapRepository:
    """Placeholder interface for reading and updating ADS roadmap artifacts."""

    def __init__(self, roadmap_path: Path) -> None:
        """Store the roadmap artifact location for a future implementation."""

        self.roadmap_path = roadmap_path

    def load(self) -> None:
        """Load the roadmap artifact when persistence behavior is defined."""

        # TODO: Parse the roadmap Markdown artifact.
        raise NotImplementedError


# TODO: Define roadmap item contracts and persistence semantics.
