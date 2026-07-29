"""LLM tool implementation for GoalOS."""

from __future__ import annotations

from app.tools.base_tool import BaseTool, ToolContext, ToolResult


class LLMTool(BaseTool):
    """LLM tool stub for future provider-backed generation."""

    def __init__(self) -> None:
        """Initialize the LLM tool.
        """

        super().__init__(
            name="llm",
            description="Provides LLM generation stubs.",
        )

    async def execute(self, context: ToolContext) -> ToolResult:
        """Execute an LLM command stub.

        Args:
            context: Tool execution context.

        Returns:
            Tool result describing the requested LLM command.
        """

        command = self._require_text(context.command, "command")
        return self.success({"command": command, "implemented": False})
