"""Review boundary for the Autonomous Development System."""

from __future__ import annotations

from app.kernel.development.models import DevelopmentTask


class DevelopmentReviewer:
    """Placeholder for reviewing ADS task outcomes."""

    def review(self, task: DevelopmentTask) -> None:
        """Review a task when review criteria are defined."""

        # TODO: Define code-quality, safety, and scope review contracts.
        raise NotImplementedError


# TODO: Add review decisions and remediation guidance.
