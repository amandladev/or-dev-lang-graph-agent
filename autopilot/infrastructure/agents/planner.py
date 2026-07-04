"""Planner agent implementation.

Uses OpenCode to analyze the ticket and context, then produces a structured
implementation plan with concrete steps for the Code_Executor to follow.
"""

import json
from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class PlannerAgent:
    """Creates an implementation plan from ticket and context.

    The Planner receives enriched ticket details and assembled context
    (from ContextBuilder), then uses OpenCode to produce a structured
    plan with actionable steps.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize PlannerAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        return "Planner"

    @property
    def description(self) -> str:
        return "Creates an implementation plan from ticket and context"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"ticket": dict, "context": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"plan": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the planner agent.

        Builds a prompt with ticket + context information, sends it to
        OpenCode, and parses the response into a structured plan.

        Args:
            state: Fields from WorkflowState. Expected: "ticket", "context".
            memory_context: Optional memory data (unused currently).

        Returns:
            Dict with "plan" containing steps list.
        """
        ticket = state.get("ticket", {})
        context = state.get("context", {})

        # Build the planning prompt
        prompt = self._build_prompt(ticket, context)

        # Execute via OpenCode
        try:
            opencode = self._tool_registry.get("opencode")
        except KeyError:
            # Fallback: generate a basic plan from ticket info
            return {"plan": self._fallback_plan(ticket)}

        result = opencode.execute(prompt=prompt)

        if result.success:
            plan = self._parse_plan(result.data.get("result", ""), ticket)
            return {"plan": plan}
        else:
            # If OpenCode fails, return a basic plan
            return {"plan": self._fallback_plan(ticket, error=result.error)}

    def _build_prompt(self, ticket: dict, context: dict) -> str:
        """Build the planning prompt for OpenCode.

        Args:
            ticket: Enriched ticket data.
            context: Assembled context from ContextBuilder.

        Returns:
            A formatted prompt string.
        """
        ticket_id = ticket.get("id", "unknown")
        title = ticket.get("title", "No title")
        description = ticket.get("description", "No description")
        labels = ticket.get("labels", [])

        # Gather context sources
        sources_text = ""
        for source in context.get("sources", []):
            source_type = source.get("type", "")
            if source_type == "jira_description":
                sources_text += f"\n--- Jira Description ---\n{source.get('content', '')}\n"
            elif source_type == "jira_comments":
                comments = source.get("content", [])
                if comments:
                    sources_text += "\n--- Recent Comments ---\n"
                    for c in comments[-3:]:
                        sources_text += f"  [{c.get('author', '')}]: {c.get('body', '')}\n"
            elif source_type == "obsidian_notes":
                titles = source.get("titles", [])
                if titles:
                    sources_text += f"\n--- Related Docs ---\n{', '.join(titles)}\n"

        # Related notes excerpts
        notes_text = ""
        for note in context.get("related_notes", [])[:3]:
            notes_text += f"\n--- {note.get('title', '')} ---\n{note.get('excerpt', '')}\n"

        prompt = f"""Analyze this ticket and create a step-by-step implementation plan.

TICKET: {ticket_id} - {title}
LABELS: {', '.join(labels) if labels else 'None'}

DESCRIPTION:
{description}

ADDITIONAL CONTEXT:
{sources_text}

RELATED DOCUMENTATION:
{notes_text}

Please respond with a clear implementation plan as a numbered list of steps.
Each step should describe:
1. What to do (specific file changes, commands to run)
2. Why (the reasoning)

Keep it practical and actionable. Focus on the code changes needed.
"""
        return prompt.strip()

    def _parse_plan(self, response: str, ticket: dict) -> dict:
        """Parse OpenCode's response into a structured plan.

        Args:
            response: Raw text response from OpenCode.
            ticket: Ticket data for metadata.

        Returns:
            Plan dict with steps list.
        """
        # Split response into steps (look for numbered items)
        steps = []
        current_step = ""
        step_num = 0

        for line in response.split("\n"):
            stripped = line.strip()
            # Detect numbered steps (1., 2., etc.)
            if stripped and stripped[0].isdigit() and "." in stripped[:4]:
                if current_step:
                    step_num += 1
                    steps.append({
                        "step": step_num,
                        "description": current_step.strip(),
                        "agent": "Code_Executor",
                    })
                current_step = stripped.split(".", 1)[-1].strip()
            elif current_step:
                current_step += " " + stripped

        # Don't forget the last step
        if current_step:
            step_num += 1
            steps.append({
                "step": step_num,
                "description": current_step.strip(),
                "agent": "Code_Executor",
            })

        # If no structured steps found, treat the whole response as one step
        if not steps:
            steps = [{
                "step": 1,
                "description": response.strip() or "Implement changes as described in ticket",
                "agent": "Code_Executor",
            }]

        return {
            "ticket_id": ticket.get("id", ""),
            "steps": steps,
            "raw_response": response,
        }

    def _fallback_plan(self, ticket: dict, error: str = "") -> dict:
        """Generate a basic fallback plan when OpenCode is unavailable.

        Args:
            ticket: Ticket data.
            error: Optional error message explaining the fallback.

        Returns:
            Simple plan dict.
        """
        title = ticket.get("title", "Implement ticket")
        steps = [
            {"step": 1, "description": f"Implement: {title}", "agent": "Code_Executor"},
        ]
        plan = {"ticket_id": ticket.get("id", ""), "steps": steps}
        if error:
            plan["fallback_reason"] = error
        return plan
