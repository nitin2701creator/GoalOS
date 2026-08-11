"""Python version compatibility helpers for GoalOS.

The codebase targets Python 3.11+ (lifecycle statuses use ``StrEnum``).
This module provides a behavior-identical fallback so the project also
imports and runs on Python 3.10 sandboxes.
"""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11

    from enum import Enum

    class StrEnum(str, Enum):
        """Backport of :class:`enum.StrEnum` for Python 3.10."""

        def __str__(self) -> str:
            return str(self.value)


__all__ = ["StrEnum"]
