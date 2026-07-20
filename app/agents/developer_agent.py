"""Developer agent implementation for GoalOS."""

from __future__ import annotations

import logging
from typing import Mapping

from app.ai.llm_gateway import LLMGateway
from app.agents.base_agent import AgentContext, AgentResult, BaseAgent
from app.skills import BaseSkill, SkillLoader
from app.tools import FileSystemTool, LLMTool

logger = logging.getLogger(__name__)


class DeveloperAgent(BaseAgent):
    """Lightweight runtime orchestrator for developer-facing resources."""

    agent_name = "developer"

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        """Initialize the developer agent."""

        super().__init__(
            name="Developer Agent",
            description="Plans, implements, and reports software engineering work.",
        )
        self._configured_llm_gateway = llm_gateway
        self._skill_loader = SkillLoader()

    def initialize(self) -> None:
        """Load developer resources and the shared LLM gateway."""

        if self.is_initialized:
            return
        self._llm_gateway = self._configured_llm_gateway or LLMGateway()
        super().initialize()
        logger.info("Developer agent runtime resources loaded")

    def load_skills(self) -> Mapping[str, BaseSkill]:
        """Discover and initialize skills through the shared skills runtime."""

        self._skill_loader.discover_skills()
        return self._skill_loader.load_skills()

    def shutdown(self) -> None:
        """Release initialized skills before clearing agent resources."""

        if self.is_initialized:
            self._skill_loader.shutdown_skills()
        super().shutdown()

    def load_tools(self) -> Mapping[str, LLMTool | FileSystemTool]:
        """Load developer-safe tools from the shared tools framework."""

        tools = (LLMTool(), FileSystemTool())
        return {tool.name: tool for tool in tools}

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

        if not self.is_initialized:
            self.initialize()
        goal = self._require_text(context.goal, "goal")
        return self._result(
            summary=f"Prepared developer runtime execution stub for: {goal}",
            actions=("Coordinate loaded skills, tools, and LLM services for the request.",),
            metadata={
                "phase": "execute",
                "skill_count": len(self.skills),
                "tool_count": len(self.tools),
                "llm_gateway_loaded": self.llm_gateway is not None,
            },
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
