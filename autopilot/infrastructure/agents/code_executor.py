"""Code Executor agent stub implementation."""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class CodeExecutorAgent:
    """Executes code changes based on the implementation plan.

    This is a stub implementation for the MVP. Future versions will
    use OpenCodeTool and FilesystemTool to implement changes.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize CodeExecutorAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        """Unique string identifier for this agent."""
        return "Code_Executor"

    @property
    def description(self) -> str:
        """Human-readable description of the agent's responsibility."""
        return "Executes code changes based on the implementation plan"

    @property
    def input_schema(self) -> dict[str, type]:
        """Typed dictionary specification of required input fields from WorkflowState."""
        return {"plan": dict, "context": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        """Typed dictionary specification of output fields written to WorkflowState."""
        return {"modified_files": list}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the code executor agent's task.

        Raises:
            NotImplementedError: Always, as this is a stub implementation.
        """
        raise NotImplementedError("Code_Executor agent is not implemented in MVP")
