"""Obsidian tool stub implementation."""

from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult


class ObsidianTool:
    """Stub tool for Obsidian vault query operations.

    Implements the ToolInterface protocol for uniform tool access.
    Not implemented in MVP.
    """

    @property
    def name(self) -> str:
        """Unique string identifier for tool lookup."""
        return "obsidian"

    @property
    def input_schema(self) -> dict[str, type]:
        """Expected input parameters."""
        return {"query": str, "vault_path": str}

    @property
    def output_schema(self) -> dict[str, type]:
        """Expected output structure on success."""
        return {"notes": list}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute is not implemented for MVP.

        Raises:
            NotImplementedError: Always, indicating stub status.
        """
        raise NotImplementedError("obsidian tool is not implemented in MVP")
