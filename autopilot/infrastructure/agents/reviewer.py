"""Reviewer agent stub implementation."""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class ReviewerAgent:
    """Reviews modified files and produces evidence of quality.

    This is a stub implementation for the MVP. Future versions will
    perform code review using LLM-based analysis.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize ReviewerAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        """Unique string identifier for this agent."""
        return "Reviewer"

    @property
    def description(self) -> str:
        """Human-readable description of the agent's responsibility."""
        return "Reviews modified files and produces evidence of quality"

    @property
    def input_schema(self) -> dict[str, type]:
        """Typed dictionary specification of required input fields from WorkflowState."""
        return {"modified_files": list, "context": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        """Typed dictionary specification of output fields written to WorkflowState."""
        return {"evidence": list}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the reviewer agent's task.

        Raises:
            NotImplementedError: Always, as this is a stub implementation.
        """
        raise NotImplementedError("Reviewer agent is not implemented in MVP")
