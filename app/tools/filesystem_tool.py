"""Filesystem tool implementation for GoalOS."""

from __future__ import annotations

from pathlib import Path

from app.tools.base_tool import BaseTool, ToolContext, ToolResult


class FileSystemTool(BaseTool):
    """Filesystem utility tool stub."""

    def __init__(self, root_path: Path | str | None = None) -> None:
        """Initialize the filesystem tool.

        Args:
            root_path: Optional root directory allowed for tool operations.
        """

        super().__init__(
            name="filesystem",
            description="Provides filesystem operation stubs.",
        )
        self.root_path = Path(root_path).resolve() if root_path is not None else None

    async def execute(self, context: ToolContext) -> ToolResult:
        """Execute a filesystem command stub.

        Args:
            context: Tool execution context.

        Returns:
            Tool result describing the requested filesystem command.
        """

        command = self._require_text(context.command, "command")
        return self.success(
            {
                "command": command,
                "implemented": False,
                "root_path": str(self.root_path) if self.root_path is not None else None,
            }
        )


FilesystemTool = FileSystemTool
