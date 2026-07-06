"""Context Builder agent implementation.

Assembles context from multiple sources:
1. Jira ticket details (title, description, comments, labels)
2. Obsidian vault notes related to the ticket
3. Optional: workspace file search for code context

The agent coordinates JiraTool and ObsidianTool to build a unified
context object that downstream agents (Planner, Code_Executor) can use.
"""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class ContextBuilderAgent:
    """Assembles context from ticket details and knowledge sources.

    Uses JiraTool to fetch ticket data and ObsidianTool to find
    related documentation. Produces a structured context dict that
    other agents consume for planning and implementation.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize ContextBuilderAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        return "Context_Builder"

    @property
    def description(self) -> str:
        return "Assembles context from ticket details and knowledge sources"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"ticket": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"ticket": dict, "context": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the context builder agent.

        1. Extract ticket ID from state
        2. Fetch full ticket details from Jira
        3. Build search query from ticket title + labels
        4. Search Obsidian vault for related notes
        5. Return enriched ticket and assembled context

        Args:
            state: Fields from WorkflowState matching input_schema.
                Expected keys: "ticket" (dict with at least "id" field).
            memory_context: Optional memory data (unused in current implementation).

        Returns:
            Dict with "ticket" (enriched) and "context" (assembled knowledge).
        """
        ticket_input = state.get("ticket", {})
        ticket_id = ticket_input.get("id", "")

        if not ticket_id:
            return {
                "ticket": ticket_input,
                "context": {"error": "No ticket ID provided", "sources": []},
            }

        # Step 1: Fetch ticket from Jira
        ticket_data = self._fetch_ticket(ticket_id)

        # Step 2: Search related notes in Obsidian
        search_query = self._build_search_query(ticket_data)
        obsidian_notes = self._search_obsidian(search_query)

        # Step 3: Assemble context
        context = {
            "sources": [],
            "related_notes": obsidian_notes,
            "search_query": search_query,
        }

        if ticket_data.get("description"):
            context["sources"].append({
                "type": "jira_description",
                "content": ticket_data["description"],
            })

        if ticket_data.get("comments"):
            context["sources"].append({
                "type": "jira_comments",
                "content": ticket_data["comments"],
            })

        if obsidian_notes:
            context["sources"].append({
                "type": "obsidian_notes",
                "count": len(obsidian_notes),
                "titles": [n.get("title", "") for n in obsidian_notes[:5]],
            })

        return {
            "ticket": ticket_data,
            "context": context,
        }

    def _fetch_ticket(self, ticket_id: str) -> dict[str, Any]:
        """Fetch ticket details from Jira.

        Args:
            ticket_id: The Jira ticket ID (e.g., "PROJ-123").

        Returns:
            Ticket data dict. On failure, returns minimal dict with ID and error.
        """
        try:
            jira = self._tool_registry.get("jira")
        except KeyError:
            return {"id": ticket_id, "error": "Jira tool not registered"}

        # Infer instance from ticket prefix if available
        instance = self._infer_instance(ticket_id)

        result = jira.execute(action="get_ticket", ticket_id=ticket_id, instance=instance)

        if result.success:
            return result.data
        else:
            # Return what we have with the error noted
            return {
                "id": ticket_id,
                "title": "",
                "description": "",
                "status": "",
                "error": result.error,
            }

    def _search_obsidian(self, query: str) -> list[dict[str, Any]]:
        """Search Obsidian vault for notes matching the query.

        Args:
            query: Search terms string.

        Returns:
            List of matching note dicts, or empty list on failure.
        """
        if not query:
            return []

        try:
            obsidian = self._tool_registry.get("obsidian")
        except KeyError:
            return []

        result = obsidian.execute(query=query, max_results=10)

        if result.success:
            return result.data or []
        else:
            return []

    def _build_search_query(self, ticket_data: dict[str, Any]) -> str:
        """Build a search query from ticket metadata.

        Combines ticket title and labels into search keywords.

        Args:
            ticket_data: The fetched ticket data dict.

        Returns:
            Space-separated search query string.
        """
        parts = []

        title = ticket_data.get("title", "")
        if title:
            # Take meaningful words from the title (skip short words)
            words = [w for w in title.split() if len(w) > 3]
            parts.extend(words[:6])  # Max 6 words from title

        labels = ticket_data.get("labels", [])
        if labels:
            parts.extend(labels[:3])  # Max 3 labels

        project = ticket_data.get("project", "")
        if project:
            parts.append(project)

        return " ".join(parts)

    def _infer_instance(self, ticket_id: str) -> str:
        """Infer the Jira instance from the ticket ID prefix.

        Maps known project prefixes to instance names. This is a simple
        heuristic — can be extended or made configurable.

        Args:
            ticket_id: The ticket ID (e.g., "WTS-123", "CULQI-456").

        Returns:
            Instance name string, or empty string if unknown.
        """
        prefix = ticket_id.split("-")[0].upper() if "-" in ticket_id else ""

        # Map known prefixes to instances
        # Extend this as needed for your projects
        prefix_map = {
            "WTS": "WTS",
            "CULQI": "CULQI",
        }

        return prefix_map.get(prefix, "")
