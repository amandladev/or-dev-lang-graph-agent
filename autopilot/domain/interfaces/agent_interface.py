"""Agent interface protocol for the domain layer."""

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class AgentInterface(Protocol):
    """Protocol that all agents must implement."""

    @property
    def name(self) -> str:
        """Unique string identifier for this agent."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of the agent's responsibility."""
        ...

    @property
    def input_schema(self) -> dict[str, type]:
        """Typed dictionary specification of required input fields from WorkflowState."""
        ...

    @property
    def output_schema(self) -> dict[str, type]:
        """Typed dictionary specification of output fields written to WorkflowState."""
        ...

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Execute the agent's task.

        Args:
            state: Fields from WorkflowState matching input_schema.
            memory_context: Optional memory data for future memory-capable agents.

        Returns:
            Dictionary of output fields matching output_schema.

        Raises:
            Exception with original type preserved on failure.
        """
        ...
