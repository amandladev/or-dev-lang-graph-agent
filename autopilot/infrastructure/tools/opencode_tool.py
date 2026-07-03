"""OpenCode tool stub implementation."""

from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult


class OpenCodeTool:
    """Stub tool for OpenCode AI coding assistant operations.

    Implements the ToolInterface protocol for uniform tool access.
    Not implemented in MVP.
    """

    @property
    def name(self) -> str:
        """Unique string identifier for tool lookup."""
        return "opencode"

    @property
    def input_schema(self) -> dict[str, type]:
        """Expected input parameters."""
        return {"prompt": str, "context": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        """Expected output structure on success."""
        return {"result": str}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute is not implemented for MVP.

        Raises:
            NotImplementedError: Always, indicating stub status.
        """
        raise NotImplementedError("opencode tool is not implemented in MVP")
