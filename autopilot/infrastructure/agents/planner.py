"""Planner agent implementation.

Uses OpenCode to analyze the ticket and context, then produces a structured
implementation plan with concrete steps for the Code_Executor to follow.

Consults the Knowledge Engine for similar past experiences to inform planning.
"""

from typing import Any

from autopilot.application.registries.tool_registry import ToolRegistry


class PlannerAgent:
    """Creates an implementation plan from ticket and context.

    The Planner receives enriched ticket details and assembled context
    (from ContextBuilder), then uses OpenCode to produce a structured
    plan with actionable steps.

    Before generating a new plan, consults the Knowledge Engine for
    similar past experiences. If found, includes them in the prompt
    to OpenCode for better planning.
    """

    def __init__(self, tool_registry: ToolRegistry, knowledge_engine=None) -> None:
        """Initialize PlannerAgent with tool registry and optional knowledge engine.

        Args:
            tool_registry: Registry for accessing tools by name.
            knowledge_engine: Optional KnowledgeEngineInterface for querying past experiences.
        """
        self._tool_registry = tool_registry
        self._knowledge_engine = knowledge_engine

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
        memory_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the planner agent.

        1. Consult Knowledge Engine for similar past experiences
        2. Build a prompt with ticket + context + past experiences
        3. Send to OpenCode and parse response into structured plan

        Args:
            state: Fields from WorkflowState. Expected: "ticket", "context".
            memory_context: Optional memory data (unused currently).

        Returns:
            Dict with "plan" containing steps list.
        """
        ticket = state.get("ticket", {})
        context = state.get("context", {})

        # Step 1: Query Knowledge Engine for relevant past experiences
        past_experiences = self._find_relevant_experiences(ticket, context)

        # Step 2: Build the planning prompt (includes past experiences if found)
        prompt = self._build_prompt(ticket, context, past_experiences)

        # Step 3: Execute via OpenCode
        try:
            opencode = self._tool_registry.get("opencode")
        except KeyError:
            return {"plan": self._fallback_plan(ticket)}

        result = opencode.execute(prompt=prompt)

        if result.success:
            plan = self._parse_plan(result.data.get("result", ""), ticket)
            return {"plan": plan}
        else:
            return {"plan": self._fallback_plan(ticket, error=result.error)}

    def _find_relevant_experiences(self, ticket: dict, context: dict) -> list:
        """Query Knowledge Engine for similar past experiences.

        Args:
            ticket: Ticket data.
            context: Assembled context.

        Returns:
            List of Experience entities (may be empty if no engine or no matches).
        """
        if not self._knowledge_engine:
            return []

        try:
            from autopilot.domain.value_objects.search_criteria import SearchCriteria

            # Build search criteria from ticket info
            title = ticket.get("title", "")
            labels = ticket.get("labels", [])
            project = ticket.get("project", "")

            criteria = SearchCriteria(
                text=title,
                tags=labels,
                domain=project.lower() if project else "",
                limit=3,
            )

            return self._knowledge_engine.find_similar(criteria)
        except Exception:
            return []  # Knowledge engine errors shouldn't break planning

    def _build_prompt(self, ticket: dict, context: dict, past_experiences: list = None) -> str:
        """Build the planning prompt for OpenCode.

        Args:
            ticket: Enriched ticket data.
            context: Assembled context from ContextBuilder.
            past_experiences: Optional list of similar past experiences.

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

        # Past experiences section
        experience_text = ""
        if past_experiences:
            experience_text = "\nPAST EXPERIENCES (similar problems solved before):\n"
            for i, exp in enumerate(past_experiences[:3], 1):
                experience_text += f"\n  {i}. [{exp.ticket_id}] {exp.objective}\n"
                if exp.solution_description:
                    experience_text += f"     Solution: {exp.solution_description[:200]}\n"
                if exp.decisions:
                    experience_text += f"     Decisions: {'; '.join(exp.decisions[:3])}\n"
                if exp.problems_encountered:
                    experience_text += f"     Problems found: {'; '.join(exp.problems_encountered[:2])}\n"
                if exp.technologies:
                    experience_text += f"     Technologies: {', '.join(exp.technologies)}\n"

        prompt = f"""Analyze this ticket and create a step-by-step implementation plan.

TICKET: {ticket_id} - {title}
LABELS: {', '.join(labels) if labels else 'None'}

DESCRIPTION:
{description}

ADDITIONAL CONTEXT:
{sources_text}

RELATED DOCUMENTATION:
{notes_text}
{experience_text}
Please respond with a clear implementation plan as a numbered list of steps.
Each step should describe:
1. What to do (specific file changes, commands to run)
2. Why (the reasoning)

Keep it practical and actionable. Focus on the code changes needed.
{('Consider the past experiences above — reuse approaches that worked.' if past_experiences else '')}
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
