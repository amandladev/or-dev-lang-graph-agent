"""Documentation agent stub implementation."""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class DocumentationAgent:
    """Generates documentation from plan, evidence, and modified files.

    This is a stub implementation for the MVP. Future versions will
    produce structured documentation drafts.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize DocumentationAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        """Unique string identifier for this agent."""
        return "Documentation_Agent"

    @property
    def description(self) -> str:
        """Human-readable description of the agent's responsibility."""
        return "Generates documentation from plan, evidence, and modified files"

    @property
    def input_schema(self) -> dict[str, type]:
        """Typed dictionary specification of required input fields from WorkflowState."""
        return {"plan": dict, "evidence": list, "modified_files": list}

    @property
    def output_schema(self) -> dict[str, type]:
        """Typed dictionary specification of output fields written to WorkflowState."""
        return {"metadata": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the documentation agent's task.

        Raises:
            NotImplementedError: Always, as this is a stub implementation.
        """
        raise NotImplementedError("Documentation_Agent agent is not implemented in MVP")
