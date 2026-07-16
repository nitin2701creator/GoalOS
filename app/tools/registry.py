"""Tool registry for GoalOS."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from app.tools.base_tool import BaseTool


class ToolRegistry:
    """Singleton in-memory registry for available GoalOS tools."""

    _instance: ToolRegistry | None = None

    def __new__(cls) -> ToolRegistry:
        """Return the singleton registry instance."""

        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(self, tool: BaseTool) -> None:
        """Register a tool by name.

        Args:
            tool: Tool instance to register.

        Raises:
            ValueError: If a tool with the same name already exists.
        """

        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> BaseTool | None:
        """Unregister a tool by name.

        Args:
            name: Tool name.

        Returns:
            The removed tool, or None when missing.
        """

        return self._tools.pop(name.strip(), None)

    def get(self, name: str) -> BaseTool | None:
        """Return a registered tool by name.

        Args:
            name: Tool name.

        Returns:
            The registered tool, or None when missing.
        """

        return self._tools.get(name.strip())

    def require(self, name: str) -> BaseTool:
        """Return a registered tool or raise an error.

        Args:
            name: Tool name.

        Returns:
            The registered tool.

        Raises:
            KeyError: If the requested tool is not registered.
        """

        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Tool not registered: {name}")
        return tool

    def list(self) -> tuple[str, ...]:
        """List registered tool names.

        Returns:
            Registered tool names in sorted order.
        """

        return tuple(sorted(self._tools))

    def list_tools(self) -> tuple[str, ...]:
        """List registered tool names.

        Returns:
            Registered tool names in sorted order.
        """

        return self.list()

    def snapshot(self) -> Mapping[str, BaseTool]:
        """Return an immutable snapshot of registered tools.

        Returns:
            Immutable mapping of tool names to tool instances.
        """

        return MappingProxyType(dict(self._tools))
