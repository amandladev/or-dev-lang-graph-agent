"""GitHub tool stub implementation."""

from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolResult


class GitHubTool:
    """Stub tool for GitHub API operations.

    Implements the ToolInterface protocol for uniform tool access.
    Not implemented in MVP.
    """

    @property
    def name(self) -> str:
        """Unique string identifier for tool lookup."""
        return "github"

    @property
    def input_schema(self) -> dict[str, type]:
        """Expected input parameters."""
        return {"action": str, "repo": str}

    @property
    def output_schema(self) -> dict[str, type]:
        """Expected output structure on success."""
        return {"result": dict}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute is not implemented for MVP.

        Raises:
            NotImplementedError: Always, indicating stub status.
        """
        raise NotImplementedError("github tool is not implemented in MVP")
