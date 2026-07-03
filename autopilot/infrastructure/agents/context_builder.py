"""Context Builder agent stub implementation."""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class ContextBuilderAgent:
    """Assembles context from ticket details and knowledge sources.

    This is a stub implementation for the MVP. Future versions will
    use JiraTool and ObsidianTool to fetch ticket details and
    related documentation.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize ContextBuilderAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        """Unique string identifier for this agent."""
        return "Context_Builder"

    @property
    def description(self) -> str:
        """Human-readable description of the agent's responsibility."""
        return "Assembles context from ticket details and knowledge sources"

    @property
    def input_schema(self) -> dict[str, type]:
        """Typed dictionary specification of required input fields from WorkflowState."""
        return {"ticket": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        """Typed dictionary specification of output fields written to WorkflowState."""
        return {"ticket": dict, "context": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the context builder agent's task.

        Raises:
            NotImplementedError: Always, as this is a stub implementation.
        """
        raise NotImplementedError("Context_Builder agent is not implemented in MVP")
