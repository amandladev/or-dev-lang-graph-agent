"""Tester agent stub implementation."""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class TesterAgent:
    """Runs tests against modified files and produces evidence.

    This is a stub implementation for the MVP. Future versions will
    execute test suites and Playwright tests.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize TesterAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        """Unique string identifier for this agent."""
        return "Tester"

    @property
    def description(self) -> str:
        """Human-readable description of the agent's responsibility."""
        return "Runs tests against modified files and produces evidence"

    @property
    def input_schema(self) -> dict[str, type]:
        """Typed dictionary specification of required input fields from WorkflowState."""
        return {"modified_files": list}

    @property
    def output_schema(self) -> dict[str, type]:
        """Typed dictionary specification of output fields written to WorkflowState."""
        return {"evidence": list}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the tester agent's task.

        Raises:
            NotImplementedError: Always, as this is a stub implementation.
        """
        raise NotImplementedError("Tester agent is not implemented in MVP")
