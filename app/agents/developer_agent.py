"""Developer agent implementation for GoalOS."""

from __future__ import annotations

from app.agents.base_agent import AgentContext, AgentResult, BaseAgent


class DeveloperAgent(BaseAgent):
    """Agent responsible for planning implementation work."""

    def __init__(self) -> None:
        """Initialize the developer agent."""

        super().__init__(
            name="Developer Agent",
            description="Plans, implements, and reports software engineering work.",
        )

    async def plan(self, context: AgentContext) -> AgentResult:
        """Create a deterministic implementation plan from context.

        Args:
            context: Immutable execution context.

        Returns:
            A developer-focused agent result.
        """

        goal = self._require_text(context.goal, "goal")
        normalized_instructions = tuple(instruction.strip() for instruction in context.instructions if instruction.strip())
        actions = (
            "Review relevant application boundaries.",
            "Design a backwards-compatible implementation path.",
            "Add focused tests for the requested behavior.",
            "Run formatting, linting, and test verification.",
        )

        if normalized_instructions:
            actions = (*actions, "Apply provided implementation constraints.")

        return self._result(
            summary=f"Prepared implementation plan for: {goal}",
            actions=actions,
            metadata={
                "phase": "plan",
                "instruction_count": len(normalized_instructions),
            },
        )

    async def execute(self, context: AgentContext) -> AgentResult:
        """Create a deterministic execution stub from context.

        Args:
            context: Immutable execution context.

        Returns:
            A developer-focused execution result.
        """

        goal = self._require_text(context.goal, "goal")
        return self._result(
            summary=f"Prepared execution stub for: {goal}",
            actions=("Await approved implementation scope before modifying code.",),
            metadata={"phase": "execute"},
        )

    async def report(self, context: AgentContext) -> AgentResult:
        """Create a deterministic progress report from context.

        Args:
            context: Immutable execution context.

        Returns:
            A developer-focused reporting result.
        """

        goal = self._require_text(context.goal, "goal")
        return self._result(
            summary=f"Prepared engineering report for: {goal}",
            actions=("Report completed work, verification status, and remaining risks.",),
            metadata={"phase": "report"},
        )
