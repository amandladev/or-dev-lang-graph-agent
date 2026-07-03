"""Tool registry for tool discovery and injection."""

from autopilot.domain.interfaces.tool_interface import ToolInterface


class ToolRegistry:
    """Registry for tool discovery and injection."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolInterface] = {}

    def register(self, tool: ToolInterface) -> None:
        """Register a tool by its name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolInterface:
        """
        Retrieve a tool by name.

        Raises:
            KeyError: If the tool name is not registered.
        """
        if name not in self._tools:
            raise KeyError(f"Tool not registered: {name}")
        return self._tools[name]
