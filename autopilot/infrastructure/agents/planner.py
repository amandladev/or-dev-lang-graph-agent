"""Planner agent implementation.

Uses OpenCode to analyze the ticket and context, then produces a structured
implementation plan with concrete steps for the Code_Executor to follow.

Consults the Knowledge Engine for similar past experiences to inform planning.
"""

import re
from typing import Any

from autopilot.application.registries.tool_registry import ToolRegistry
from autopilot.domain.value_objects.exceptions import NeedsClarificationError

# Marker OpenCode is instructed to use as the *entire* response when the
# ticket is too ambiguous to plan confidently. Checked as an exact line
# prefix (not a substring) so a step description that happens to mention
# "needs clarification" in prose is never mistaken for the marker.
CLARIFICATION_MARKER = "NEEDS_CLARIFICATION:"


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
        return {"ticket": dict, "context": dict, "workspace": dict}

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
        workspace = state.get("workspace", {})
        workspace = workspace if isinstance(workspace, dict) else {}

        past_experiences = self._find_relevant_experiences(ticket, context)

        prompt = self._build_prompt(ticket, context, past_experiences)

        try:
            opencode = self._tool_registry.get("opencode")
        except KeyError:
            return {"plan": self._fallback_plan(ticket)}

        result = opencode.execute(prompt=prompt, cwd=workspace.get("path", ""))

        if result.success:
            raw = result.data.get("result", "")
            question = self._extract_clarification(raw)
            if question:
                raise NeedsClarificationError(question)
            plan = self._parse_plan(raw, ticket)
            return {"plan": plan}
        else:
            return {"plan": self._fallback_plan(ticket, error=result.error)}

    @staticmethod
    def _extract_clarification(response: str) -> str | None:
        """Detect OpenCode asking for clarification instead of planning.

        The prompt instructs OpenCode to respond with a single line starting
        with the CLARIFICATION_MARKER when the ticket is genuinely too
        ambiguous to plan. Only the first non-blank line is checked, so a
        plan step that happens to mention the phrase mid-response doesn't
        false-positive.

        Args:
            response: Raw text response from OpenCode.

        Returns:
            The question text if the marker was found, else None.
        """
        for line in response.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(CLARIFICATION_MARKER):
                question = stripped[len(CLARIFICATION_MARKER):].strip()
                return question or "Clarification needed (no question text provided)."
            return None
        return None

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

        # A prior clarification round-trip: the human's answer to a question
        # this same Planner raised on an earlier attempt (see resume_command).
        clarification_text = ""
        clarification_answer = context.get("clarification_answer")
        if clarification_answer:
            clarification_question = context.get("clarification_question", "")
            clarification_text = (
                "\nHUMAN CLARIFICATION (you asked this on a previous attempt "
                "and a human answered — use it to resolve the ambiguity and "
                "produce the plan now):\n"
                f"  Q: {clarification_question}\n"
                f"  A: {clarification_answer}\n"
            )

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
{clarification_text}
If — and only if — this ticket is genuinely ambiguous (e.g. it allows two
materially different valid implementations and picking wrong would mean
redoing the work), respond with EXACTLY ONE line and nothing else:
{CLARIFICATION_MARKER} <your specific question>
Prefer making a reasonable, stated assumption and producing a real plan
whenever you can — only ask if you truly cannot proceed safely.

Otherwise, respond with a clear implementation plan as a numbered list of
steps. Use strictly this format — every step starts on its own line with
the plain number and a period (e.g. `1. ` / `2. `), no markdown headers
like `**Step 1**`, no sub-numbering:
1. What to do (specific file changes)
2. Why (the reasoning)
3. Which repository-relative files and modules are expected to change
4. Any ticket IDs this work depends on, if applicable

Keep it practical and actionable. Focus on the code changes needed.
IMPORTANT: Do NOT include any git or version-control operations in the steps
(branching, checkout, commit, push, pull, rebase, merge, reset). Autopilot
handles branching, committing and pushing automatically after implementation.
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
        # Split response into steps. Accept two header styles: plain
        # numbered items ("2. ") and markdown bold headers ("**Step 2 —**"),
        # since prompts cannot force one exact format on the LLM.
        step_header = re.compile(
            r"^(?:\d+\.\s|\*{0,2}\s*step\s*\d+\b[\s:.—-]*)",
            re.IGNORECASE,
        )
        has_numbered_header = re.compile(r"^(?:\d+\.|\**\s*step\s*\d+\b)", re.IGNORECASE)

        steps: list[dict] = []
        current_step = ""
        step_num = 0

        for line in response.split("\n"):
            stripped = line.strip()
            if stripped and has_numbered_header.match(stripped):
                if current_step:
                    step_num += 1
                    steps.append({
                        "step": step_num,
                        "description": current_step.strip(),
                        "agent": "Code_Executor",
                    })
                current_step = step_header.sub("", stripped).strip()
                current_step = current_step.removesuffix("**").strip()
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

        expected_files = sorted({
            path for step in steps for path in self._extract_files(step["description"])
        })
        affected_modules = sorted({
            "/".join(path.split("/")[:2])
            for path in expected_files
            if "/" in path
        })
        depends_on = sorted({
            dependency
            for dependency in re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", response)
            if dependency != ticket.get("id", "")
        })

        return {
            "ticket_id": ticket.get("id", ""),
            "steps": steps,
            "raw_response": response,
            "expected_files": expected_files,
            "affected_modules": affected_modules,
            "depends_on": depends_on,
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
        plan["expected_files"] = []
        plan["affected_modules"] = []
        plan["depends_on"] = []
        if error:
            plan["fallback_reason"] = error
        return plan

    @staticmethod
    def _extract_files(description: str) -> list[str]:
        """Extract likely repository-relative file paths from a plan step."""
        candidates = re.findall(r"(?<![\w./-])(?:[\w.-]+/)+[\w.-]+", description)
        return sorted({path.rstrip(".,:;)") for path in candidates if "." in path})
