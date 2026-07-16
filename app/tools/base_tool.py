"""Base tool primitives for GoalOS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Immutable input context for tool execution.

    Attributes:
        command: Tool command or operation name.
        arguments: Structured command arguments.
        metadata: Optional execution metadata.
    """

    command: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize mutable mappings into immutable mappings."""

        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Immutable result returned by a tool.

    Attributes:
        tool_name: Name of the tool that produced the result.
        success: Whether the tool completed successfully.
        output: Structured tool output.
        error: Optional error message for failed executions.
    """

    tool_name: str
    success: bool
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        """Normalize mutable output into an immutable mapping."""

        object.__setattr__(self, "output", MappingProxyType(dict(self.output)))


class BaseTool(ABC):
    """Abstract base class for deterministic GoalOS tools."""

    name: str
    description: str

    def __init__(self, name: str, description: str) -> None:
        """Initialize a tool.

        Args:
            name: Unique tool name.
            description: Human-readable tool description.

        Raises:
            ValueError: If name or description is blank.
        """

        self.name = self._require_text(name, "name")
        self.description = self._require_text(description, "description")

    @abstractmethod
    async def execute(self, context: ToolContext) -> ToolResult:
        """Execute the tool with the provided context.

        Args:
            context: Immutable tool execution context.

        Returns:
            Tool execution result.
        """

    def success(self, output: Mapping[str, Any] | None = None) -> ToolResult:
        """Build a successful result.

        Args:
            output: Optional structured output.

        Returns:
            A successful tool result.
        """

        return ToolResult(tool_name=self.name, success=True, output=output or {})

    def failure(self, error: str, output: Mapping[str, Any] | None = None) -> ToolResult:
        """Build a failed result.

        Args:
            error: Human-readable error message.
            output: Optional structured output.

        Returns:
            A failed tool result.
        """

        return ToolResult(
            tool_name=self.name,
            success=False,
            output=output or {},
            error=self._require_text(error, "error"),
        )

    def _require_text(self, value: str, field_name: str) -> str:
        """Normalize a required text value."""

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"{field_name} is required")
        return normalized_value
