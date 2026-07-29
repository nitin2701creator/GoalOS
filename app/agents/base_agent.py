"""Base agent primitives for GoalOS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from app.ai.llm_gateway import LLMGateway
from app.tools.base_tool import BaseTool


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
    """Abstract orchestration shell shared by GoalOS runtime agents.

    Concrete agents supply their domain resources and execution behaviour. This
    class deliberately owns no business decisions; it only manages the agent
    lifecycle and exposes immutable resource snapshots.
    """

    name: str
    description: str
    agent_name: str

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
        self._skills: Mapping[str, Any] = MappingProxyType({})
        self._tools: Mapping[str, BaseTool] = MappingProxyType({})
        self._llm_gateway: LLMGateway | None = None
        self._initialized = False

    @property
    def skills(self) -> Mapping[str, Any]:
        """Return the immutable skills currently loaded for this agent."""

        return self._skills

    @property
    def tools(self) -> Mapping[str, BaseTool]:
        """Return the immutable tools currently loaded for this agent."""

        return self._tools

    @property
    def llm_gateway(self) -> LLMGateway | None:
        """Return the shared LLM gateway assigned during initialization."""

        return self._llm_gateway

    @property
    def is_initialized(self) -> bool:
        """Indicate whether this agent's runtime resources are available."""

        return self._initialized

    def initialize(self) -> None:
        """Load agent resources once and make the agent ready for execution."""

        if self._initialized:
            return

        self._skills = self._freeze_resources(self.load_skills())
        self._tools = self._freeze_resources(self.load_tools())
        self._initialized = True

    def shutdown(self) -> None:
        """Release runtime resource references held by this agent."""

        self._skills = MappingProxyType({})
        self._tools = MappingProxyType({})
        self._llm_gateway = None
        self._initialized = False

    def load_skills(self) -> Mapping[str, Any] | Iterable[tuple[str, Any]]:
        """Load skills available to this agent.

        Subclasses override this hook when they have skill resources. The
        default keeps agents with no skills valid without adding business logic
        to the runtime base class.
        """

        return {}

    def load_tools(self) -> Mapping[str, BaseTool] | Iterable[tuple[str, BaseTool]]:
        """Load tools available to this agent.

        Subclasses override this hook when they have tool resources.
        """

        return {}

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

    @staticmethod
    def _freeze_resources(
        resources: Mapping[str, Any] | Iterable[tuple[str, Any]],
    ) -> Mapping[str, Any]:
        """Normalize named resources into an immutable mapping."""

        return MappingProxyType(dict(resources))
