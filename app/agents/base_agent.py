"""Base agent primitives for GoalOS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Immutable input context for an agent execution.

    Attributes:
        goal: The business or technical goal the agent should support.
        instructions: Specific execution instructions for the agent.
        metadata: Optional structured metadata for the execution.
    """

    goal: str
    instructions: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize mutable metadata into an immutable mapping."""

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Immutable result produced by an agent.

    Attributes:
        agent_name: Name of the agent that produced the result.
        summary: Concise summary of the agent output.
        actions: Ordered action recommendations or completed actions.
        metadata: Optional structured metadata about the result.
    """

    agent_name: str
    summary: str
    actions: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize mutable metadata into an immutable mapping."""

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class BaseAgent(ABC):
    """Abstract base class for deterministic GoalOS agents."""

    name: str
    description: str

    def __init__(self, name: str, description: str) -> None:
        """Initialize the base agent.

        Args:
            name: Human-readable agent name.
            description: Human-readable agent description.

        Raises:
            ValueError: If the name or description is blank.
        """

        self.name = self._require_text(name, "name")
        self.description = self._require_text(description, "description")

    @abstractmethod
    async def plan(self, context: AgentContext) -> AgentResult:
        """Plan work for the provided context.

        Args:
            context: Immutable execution context.

        Returns:
            The agent planning result.
        """

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        """Execute work for the provided context.

        Args:
            context: Immutable execution context.

        Returns:
            The agent execution result.
        """

    @abstractmethod
    async def report(self, context: AgentContext) -> AgentResult:
        """Report work status for the provided context.

        Args:
            context: Immutable execution context.

        Returns:
            The agent reporting result.
        """

    def _result(
        self,
        summary: str,
        actions: tuple[str, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        """Build a normalized result for subclasses.

        Args:
            summary: Concise result summary.
            actions: Optional ordered actions.
            metadata: Optional structured metadata.

        Returns:
            A normalized agent result.
        """

        return AgentResult(
            agent_name=self.name,
            summary=self._require_text(summary, "summary"),
            actions=actions or (),
            metadata=metadata or {},
        )

    def _require_text(self, value: str, field_name: str) -> str:
        """Normalize a required text value.

        Args:
            value: Text value to normalize.
            field_name: Field name to include in validation errors.

        Returns:
            The trimmed text value.

        Raises:
            ValueError: If the value is blank.
        """

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"{field_name} is required")
        return normalized_value
