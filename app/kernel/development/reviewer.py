"""Review boundary for the Autonomous Development System."""

from __future__ import annotations

from dataclasses import dataclass

from app.kernel.development.models import DevelopmentTask


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """The decision produced by an independent code review."""

    approved: bool
    summary: str = ""


class DevelopmentReviewer:
    """Review ADS task outcomes."""

    def review(self, task: DevelopmentTask) -> ReviewResult:
        """Return a successful baseline review decision."""

        return ReviewResult(approved=True, summary="Review approved.")
