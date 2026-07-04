"""Documentation agent implementation.

Generates a summary of the work done for documentation purposes.
Produces a structured summary that can be stored in Obsidian or
added as a Jira comment.
"""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class DocumentationAgent:
    """Generates documentation from plan, evidence, and modified files.

    Produces a structured summary of the workflow execution including:
    - What was done (plan steps executed)
    - What changed (files modified)
    - Test results (evidence)
    - Publishing results (branch, commit)

    The summary is stored in metadata for optional Obsidian note creation.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize DocumentationAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        return "Documentation_Agent"

    @property
    def description(self) -> str:
        return "Generates documentation from plan, evidence, and modified files"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"plan": dict, "evidence": list, "modified_files": list}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"metadata": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Generate a documentation summary of the work performed.

        Args:
            state: Fields from WorkflowState.
                Expected: "plan", "evidence", "modified_files".
            memory_context: Optional memory data (unused currently).

        Returns:
            Dict with "metadata" containing the documentation summary.
        """
        plan = state.get("plan", {})
        evidence = state.get("evidence", [])
        modified_files = state.get("modified_files", [])

        # Build summary
        summary = self._build_summary(plan, evidence, modified_files)

        return {
            "metadata": {
                "documentation_draft": summary,
                "documentation_status": "generated",
            }
        }

    def _build_summary(
        self, plan: dict, evidence: list, modified_files: list
    ) -> str:
        """Build a markdown-formatted summary of the work done.

        Args:
            plan: The execution plan.
            evidence: Test results and other evidence.
            modified_files: List of modified file paths.

        Returns:
            Markdown-formatted summary string.
        """
        ticket_id = plan.get("ticket_id", "unknown")
        steps = plan.get("steps", [])

        lines = [
            f"# Work Summary: {ticket_id}",
            "",
            "## Plan Executed",
            "",
        ]

        for step in steps:
            num = step.get("step", "?")
            desc = step.get("description", "")
            lines.append(f"{num}. {desc}")

        lines.extend(["", "## Modified Files", ""])
        if modified_files:
            for f in modified_files:
                lines.append(f"- `{f}`")
        else:
            lines.append("- No files tracked")

        lines.extend(["", "## Test Results", ""])
        if evidence:
            for e in evidence:
                status = e.get("data", {}).get("status", "unknown")
                desc = e.get("description", "")
                lines.append(f"- {desc}: **{status}**")
        else:
            lines.append("- No test evidence recorded")

        return "\n".join(lines)
