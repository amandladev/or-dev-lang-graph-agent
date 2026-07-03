"""Planner agent implementation."""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class PlannerAgent:
    """Creates an implementation plan from ticket and context.

    The Planner agent receives ticket details and assembled context,
    then produces a structured plan with implementation steps.
    This is placeholder logic for the MVP — future versions will
    use LLM-based planning via tools.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize PlannerAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        """Unique string identifier for this agent."""
        return "Planner"

    @property
    def description(self) -> str:
        """Human-readable description of the agent's responsibility."""
        return "Creates an implementation plan from ticket and context"

    @property
    def input_schema(self) -> dict[str, type]:
        """Typed dictionary specification of required input fields from WorkflowState."""
        return {"ticket": dict, "context": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        """Typed dictionary specification of output fields written to WorkflowState."""
        return {"plan": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the planner agent's task.

        Takes ticket and context from state, produces a plan with
        implementation steps. This is placeholder logic for the MVP.

        When memory_context is None, executes identically to without
        memory support (no behavioral difference).

        Args:
            state: Fields from WorkflowState matching input_schema.
                   Expected keys: "ticket", "context".
            memory_context: Optional memory data for future memory-capable agents.

        Returns:
            Dictionary with "plan" key containing steps list.
        """
        ticket = state.get("ticket", {})
        _context = state.get("context", {})  # noqa: F841 - reserved for future planning logic

        # Placeholder planning logic for MVP
        ticket_id = ticket.get("id", "unknown")
        ticket_title = ticket.get("title", "Untitled")

        steps = [
            {
                "step": 1,
                "description": f"Analyze ticket {ticket_id}: {ticket_title}",
                "agent": "Context_Builder",
            },
            {
                "step": 2,
                "description": "Implement changes based on plan",
                "agent": "Code_Executor",
            },
            {
                "step": 3,
                "description": "Run tests and validate implementation",
                "agent": "Tester",
            },
            {
                "step": 4,
                "description": "Publish results and update ticket",
                "agent": "Publisher",
            },
            {
                "step": 5,
                "description": "Generate documentation",
                "agent": "Documentation_Agent",
            },
        ]

        return {"plan": {"steps": steps}}
