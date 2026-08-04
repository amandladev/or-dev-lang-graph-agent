"""Git tool stub implementation."""

from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolResult


class GitTool:
    """Stub tool for Git operations.

    Implements the ToolInterface protocol for uniform tool access.
    Not implemented in MVP.
    """

    @property
    def name(self) -> str:
        """Unique string identifier for tool lookup."""
        return "git"

    @property
    def input_schema(self) -> dict[str, type]:
        """Expected input parameters."""
        return {"command": str, "args": list}

    @property
    def output_schema(self) -> dict[str, type]:
        """Expected output structure on success."""
        return {"result": str}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute is not implemented for MVP.

        Raises:
            NotImplementedError: Always, indicating stub status.
        """
        raise NotImplementedError("git tool is not implemented in MVP")
