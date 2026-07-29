"""Immutable summaries exchanged between executives and the CEO."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ExecutiveSummary:
    """Normalized status report supplied by one department executive."""

    department: str
    status: str
    kpis: Mapping[str, Any] = field(default_factory=dict)
    priorities: tuple[str, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "department", self._require_text(self.department, "department"))
        object.__setattr__(self, "status", self._require_text(self.status, "status"))
        object.__setattr__(self, "kpis", MappingProxyType(dict(self.kpis)))
        object.__setattr__(self, "priorities", tuple(self.priorities))
        object.__setattr__(self, "recommendations", tuple(self.recommendations))

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not (normalized := value.strip()):
            raise ValueError(f"{field_name} is required")
        return normalized


@dataclass(frozen=True, slots=True)
class PriorityAction:
    """A department action ordered for the CEO's attention."""

    department: str
    action: str
    rank: int


@dataclass(frozen=True, slots=True)
class ExecutiveBrief:
    """Merged daily CEO briefing across registered departments."""

    department_summaries: tuple[ExecutiveSummary, ...] = field(default_factory=tuple)
    top_risks: tuple[str, ...] = field(default_factory=tuple)
    top_opportunities: tuple[str, ...] = field(default_factory=tuple)
    today_priorities: tuple[PriorityAction, ...] = field(default_factory=tuple)
    ai_recommendations: tuple[str, ...] = field(default_factory=tuple)
