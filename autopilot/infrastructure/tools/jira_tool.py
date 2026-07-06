"""Jira tool implementation for fetching and modifying ticket details via REST API.

Supports multiple Jira instances configured via environment variables:
- JIRA_<INSTANCE>_URL: Base URL (e.g., https://company.atlassian.net)
- JIRA_<INSTANCE>_EMAIL: Account email
- JIRA_<INSTANCE>_TOKEN: API token

The instance is inferred from the ticket ID prefix or can be specified explicitly.

Actions:
    - get_ticket: Fetch ticket details by ID
    - get_transitions: List available transitions for a ticket
    - apply_transition: Apply a transition by name (case-insensitive)
    - comment: Post a comment (auto-converts Markdown to Jira wiki markup)
    - create_subtask: Create a subtask under a parent ticket
    - search_jql: Search issues using JQL
    - status_entered_at: Get timestamp of last transition into a status
"""

import os
import re
import urllib.request
import urllib.error
import urllib.parse
import base64
import json
from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult


def markdown_to_wiki(md: str) -> str:
    """Convert Markdown to Jira wiki markup.

    Handles: fenced code blocks, tables, headings, lists, bold, inline code,
    links, horizontal rules. Passes through [~accountid:...] mentions unchanged.
    """
    out: list[str] = []
    in_code = False
    for line in md.splitlines():
        fence = re.match(r"^\s*```(\w+)?\s*$", line)
        if fence:
            lang = fence.group(1)
            out.append("{code:%s}" % lang if lang and not in_code else "{code}")
            in_code = not in_code
            continue
        if in_code:
            out.append(line)
            continue
        if re.match(r"^\s*\|[\s:\-|]+\|\s*$", line):
            if out and out[-1].lstrip().startswith("|"):
                cells = [c.strip() for c in out.pop().strip().strip("|").split("|")]
                out.append("||" + "||".join(cells) + "||")
            continue
        if re.match(r"^\s*-{3,}\s*$", line):
            out.append("----")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            line = f"h{len(m.group(1))}. {m.group(2)}"
        else:
            m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
            if m:
                line = "*" * (len(m.group(1)) // 2 + 1) + " " + m.group(2)
            else:
                m = re.match(r"^(\s*)\d+[.)]\s+(.*)$", line)
                if m:
                    line = "#" * (len(m.group(1)) // 2 + 1) + " " + m.group(2)
        line = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)
        line = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"{{\1}}", line)
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"[\1|\2]", line)
        out.append(line)
    return "\n".join(out)


class JiraTool:
    """Tool for interacting with Jira via REST API.

    Supports multiple Jira instances. Credentials are loaded from
    environment variables following the pattern JIRA_<INSTANCE>_<FIELD>.

    Actions:
        - "get_ticket": Fetch ticket details by ID
        - "get_transitions": List available transitions for a ticket
        - "apply_transition": Apply a transition by name
        - "comment": Post a comment (auto-converts Markdown to wiki markup)
        - "create_subtask": Create a subtask under a parent ticket
        - "search_jql": Search issues using JQL
        - "status_entered_at": Get timestamp of last transition into a status
    """

    def __init__(self, default_instance: str = "CULQI") -> None:
        """Initialize JiraTool.

        Args:
            default_instance: Default Jira instance name for env var lookup.
                Used when the ticket ID doesn't map to a known instance.
        """
        self._default_instance = default_instance

    @property
    def name(self) -> str:
        return "jira"

    @property
    def input_schema(self) -> dict[str, type]:
        return {
            "action": str,
            "ticket_id": str,
            "instance": str,
            "transition_name": str,
            "body": str,
            "jql": str,
            "fields": str,
            "max_results": int,
            "parent_key": str,
            "summary": str,
            "description": str,
            "labels": str,
            "assignee": str,
            "issuetype": str,
        }

    @property
    def output_schema(self) -> dict[str, type]:
        return {"result": dict}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a Jira operation.

        Args:
            action: The operation to perform.
            ticket_id: The Jira ticket ID (e.g., "PROJ-123").
            instance: Optional Jira instance name override.
            transition_name: Transition name for apply_transition.
            body: Comment text for comment action (Markdown, auto-converted to wiki).
            jql: JQL query for search_jql action.
            fields: Comma-separated fields for search_jql.
            max_results: Max results for search_jql (default: 50).
            parent_key: Parent ticket key for create_subtask.
            summary: Subtask summary for create_subtask.
            description: Subtask description for create_subtask.
            labels: Comma-separated labels for create_subtask.
            assignee: Account ID for create_subtask.
            issuetype: Issue type for create_subtask (default: "Subtask").

        Returns:
            ToolResult with operation result on success, error description on failure.
        """
        action = kwargs.get("action", "get_ticket")
        ticket_id = kwargs.get("ticket_id", "")
        instance = kwargs.get("instance", "")

        if action not in ("search_jql",) and not ticket_id:
            return ToolResult(success=False, error="Missing required parameter: ticket_id")

        action_map = {
            "get_ticket": lambda: self._get_ticket(ticket_id, instance),
            "get_transitions": lambda: self._get_transitions(ticket_id, instance),
            "apply_transition": lambda: self._apply_transition(
                ticket_id, kwargs.get("transition_name", ""), instance
            ),
            "comment": lambda: self._comment(ticket_id, kwargs.get("body", ""), instance),
            "create_subtask": lambda: self._create_subtask(
                ticket_id,
                kwargs.get("summary", ""),
                kwargs.get("description", ""),
                kwargs.get("labels", ""),
                kwargs.get("assignee", ""),
                kwargs.get("issuetype", "Subtask"),
                instance,
            ),
            "search_jql": lambda: self._search_jql(
                kwargs.get("jql", ""),
                kwargs.get("fields", "summary,status,assignee"),
                kwargs.get("max_results", 50),
                instance,
            ),
            "status_entered_at": lambda: self._status_entered_at(
                ticket_id, kwargs.get("status_name", ""), instance
            ),
        }

        handler = action_map.get(action)
        if handler is None:
            return ToolResult(success=False, error=f"Unsupported action: {action}")
        return handler()

    def _get_ticket(self, ticket_id: str, instance: str = "") -> ToolResult:
        """Fetch a ticket from Jira REST API.

        Args:
            ticket_id: The ticket ID (e.g., "PROJ-123").
            instance: Instance name for env var lookup. If empty, uses default.

        Returns:
            ToolResult with parsed ticket data.
        """
        instance_name = instance or self._default_instance

        # Load credentials from environment
        creds = self._load_credentials(instance_name)
        if creds is None:
            return ToolResult(
                success=False,
                error=f"Jira credentials not found for instance '{instance_name}'. "
                f"Set JIRA_{instance_name}_URL, JIRA_{instance_name}_EMAIL, "
                f"JIRA_{instance_name}_TOKEN environment variables.",
            )

        base_url, email, token = creds

        # Build the API request
        url = f"{base_url.rstrip('/')}/rest/api/3/issue/{ticket_id}"

        try:
            # Create auth header (Basic auth with email:token)
            auth_string = base64.b64encode(f"{email}:{token}".encode()).decode()
            headers = {
                "Authorization": f"Basic {auth_string}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            request = urllib.request.Request(url, headers=headers, method="GET")

            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode())

            # Extract relevant fields
            fields = data.get("fields", {})
            ticket_data = {
                "id": data.get("key", ticket_id),
                "title": fields.get("summary", ""),
                "description": self._extract_description(fields.get("description")),
                "status": fields.get("status", {}).get("name", ""),
                "assignee": fields.get("assignee", {}).get("displayName", "") if fields.get("assignee") else "",
                "priority": fields.get("priority", {}).get("name", "") if fields.get("priority") else "",
                "labels": fields.get("labels", []),
                "type": fields.get("issuetype", {}).get("name", "") if fields.get("issuetype") else "",
                "project": fields.get("project", {}).get("key", "") if fields.get("project") else "",
                "created": fields.get("created", ""),
                "updated": fields.get("updated", ""),
                "comments": self._extract_comments(fields.get("comment", {})),
            }

            return ToolResult(success=True, data=ticket_data)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ToolResult(success=False, error=f"Ticket not found: {ticket_id}")
            elif e.code == 401:
                return ToolResult(success=False, error=f"Authentication failed for Jira instance '{instance_name}'")
            elif e.code == 403:
                return ToolResult(success=False, error=f"Permission denied for ticket {ticket_id}")
            else:
                return ToolResult(success=False, error=f"Jira API error (HTTP {e.code}): {e.reason}")
        except urllib.error.URLError as e:
            return ToolResult(success=False, error=f"Connection error to Jira: {e.reason}")
        except json.JSONDecodeError:
            return ToolResult(success=False, error="Invalid JSON response from Jira API")
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error fetching ticket: {e}")

    def _load_credentials(self, instance: str) -> tuple[str, str, str] | None:
        """Load Jira credentials from environment variables.

        Looks for JIRA_<INSTANCE>_URL, JIRA_<INSTANCE>_EMAIL, JIRA_<INSTANCE>_TOKEN.
        Also tries common alternative patterns (e.g., JIRA_WTS_TOKEN).

        Returns:
            Tuple of (base_url, email, token) or None if not found.
        """
        url = os.environ.get(f"JIRA_{instance}_URL", "")
        email = os.environ.get(f"JIRA_{instance}_EMAIL", "")
        token = os.environ.get(f"JIRA_{instance}_TOKEN", "")

        if url and email and token:
            return url, email, token

        return None

    def _extract_description(self, description: Any) -> str:
        """Extract plain text from Jira's Atlassian Document Format (ADF).

        Jira API v3 returns description as ADF JSON. This extracts text content.

        Args:
            description: The description field (ADF dict or None).

        Returns:
            Plain text description string.
        """
        if description is None:
            return ""
        if isinstance(description, str):
            return description

        # ADF format: walk the content tree and extract text nodes
        texts = []
        self._walk_adf(description, texts)
        return "\n".join(texts)

    def _walk_adf(self, node: Any, texts: list[str]) -> None:
        """Recursively walk an ADF node tree extracting text."""
        if not isinstance(node, dict):
            return

        if node.get("type") == "text":
            text = node.get("text", "")
            if text:
                texts.append(text)

        for child in node.get("content", []):
            self._walk_adf(child, texts)

    def _extract_comments(self, comment_data: dict) -> list[dict[str, str]]:
        """Extract comments from Jira comment field.

        Args:
            comment_data: The comment field from Jira API response.

        Returns:
            List of comment dicts with author and body.
        """
        comments = []
        for comment in comment_data.get("comments", []):
            body = self._extract_description(comment.get("body"))
            author = comment.get("author", {}).get("displayName", "Unknown")
            created = comment.get("created", "")
            comments.append({
                "author": author,
                "body": body,
                "created": created,
            })
        return comments[-5:]  # Last 5 comments only

    def _request(
        self,
        method: str,
        path: str,
        instance: str = "",
        body: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Make an authenticated request to Jira REST API.

        Args:
            method: HTTP method (GET, POST, PUT).
            path: API path (e.g., "/rest/api/2/issue/PROJ-123").
            instance: Instance name for credential lookup.
            body: Optional JSON body.
            params: Optional query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            RuntimeError: On HTTP errors.
        """
        instance_name = instance or self._default_instance
        creds = self._load_credentials(instance_name)
        if creds is None:
            raise RuntimeError(
                f"Jira credentials not found for instance '{instance_name}'. "
                f"Set JIRA_{instance_name}_URL, JIRA_{instance_name}_EMAIL, "
                f"JIRA_{instance_name}_TOKEN environment variables."
            )

        base_url, email, token = creds
        url = f"{base_url.rstrip('/')}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        data = json.dumps(body).encode("utf-8") if body is not None else None
        auth_string = base64.b64encode(f"{email}:{token}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_string}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8")
                return json.loads(text) if text.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:800]
            raise RuntimeError(f"Jira {method} {path} -> HTTP {e.code}: {detail}") from e

    def _get_transitions(self, ticket_id: str, instance: str = "") -> ToolResult:
        """List available transitions for a ticket.

        Args:
            ticket_id: The Jira ticket ID.
            instance: Instance name override.

        Returns:
            ToolResult with list of {id, name} transitions.
        """
        try:
            out = self._request("GET", f"/rest/api/2/issue/{ticket_id}/transitions", instance)
            transitions = [{"id": t["id"], "name": t["name"]} for t in out.get("transitions", [])]
            return ToolResult(success=True, data={"transitions": transitions})
        except RuntimeError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error listing transitions: {e}")

    def _apply_transition(self, ticket_id: str, transition_name: str, instance: str = "") -> ToolResult:
        """Apply a transition by name (case-insensitive).

        Args:
            ticket_id: The Jira ticket ID.
            transition_name: Name of the transition to apply.
            instance: Instance name override.

        Returns:
            ToolResult with applied transition info.
        """
        if not transition_name:
            return ToolResult(success=False, error="Missing required parameter: transition_name")

        try:
            out = self._request("GET", f"/rest/api/2/issue/{ticket_id}/transitions", instance)
            match = next(
                (t for t in out.get("transitions", [])
                 if t["name"].strip().upper() == transition_name.strip().upper()),
                None,
            )
            if not match:
                names = ", ".join(t["name"] for t in out.get("transitions", []))
                return ToolResult(
                    success=False,
                    error=f"Transition '{transition_name}' not available for {ticket_id}. "
                          f"Available: {names}",
                )
            self._request(
                "POST",
                f"/rest/api/2/issue/{ticket_id}/transitions",
                instance,
                body={"transition": {"id": match["id"]}},
            )
            return ToolResult(success=True, data={"applied": match["name"], "id": match["id"]})
        except RuntimeError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error applying transition: {e}")

    def _comment(self, ticket_id: str, body: str, instance: str = "") -> ToolResult:
        """Post a comment on a ticket. Auto-converts Markdown to Jira wiki markup.

        Args:
            ticket_id: The Jira ticket ID.
            body: Comment text in Markdown format.
            instance: Instance name override.

        Returns:
            ToolResult with comment id and created timestamp.
        """
        if not body:
            return ToolResult(success=False, error="Missing required parameter: body")

        try:
            wiki_body = markdown_to_wiki(body)
            out = self._request(
                "POST",
                f"/rest/api/2/issue/{ticket_id}/comment",
                instance,
                body={"body": wiki_body},
            )
            return ToolResult(success=True, data={"id": out.get("id"), "created": out.get("created")})
        except RuntimeError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error posting comment: {e}")

    def _create_subtask(
        self,
        parent_key: str,
        summary: str,
        description: str,
        labels: str = "",
        assignee: str = "",
        issuetype: str = "Subtask",
        instance: str = "",
    ) -> ToolResult:
        """Create a subtask under a parent ticket.

        Args:
            parent_key: Parent ticket key (e.g., "PROJ-123").
            summary: Subtask summary.
            description: Subtask description (Markdown, auto-converted to wiki).
            labels: Comma-separated labels.
            assignee: Account ID to assign the subtask to.
            issuetype: Issue type name (default: "Subtask").
            instance: Instance name override.

        Returns:
            ToolResult with new subtask key and id.
        """
        if not summary:
            return ToolResult(success=False, error="Missing required parameter: summary")
        if not description:
            return ToolResult(success=False, error="Missing required parameter: description")

        try:
            fields: dict[str, Any] = {
                "project": {"key": parent_key.split("-")[0]},
                "parent": {"key": parent_key},
                "issuetype": {"name": issuetype},
                "summary": summary,
                "description": markdown_to_wiki(description),
            }
            if assignee:
                fields["assignee"] = {"accountId": assignee}
            if labels:
                fields["labels"] = [s.strip() for s in labels.split(",") if s.strip()]

            out = self._request("POST", "/rest/api/2/issue", instance, body={"fields": fields})
            return ToolResult(success=True, data={"key": out.get("key"), "id": out.get("id")})
        except RuntimeError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error creating subtask: {e}")

    def _search_jql(
        self,
        jql: str,
        fields: str = "summary,status,assignee",
        max_results: int = 50,
        instance: str = "",
    ) -> ToolResult:
        """Search issues using JQL.

        Args:
            jql: JQL query string.
            fields: Comma-separated field names to return.
            max_results: Maximum number of results (default: 50).
            instance: Instance name override.

        Returns:
            ToolResult with list of matching issues.
        """
        if not jql:
            return ToolResult(success=False, error="Missing required parameter: jql")

        try:
            params = {"jql": jql, "fields": fields, "maxResults": max_results}
            try:
                out = self._request("GET", "/rest/api/3/search/jql", instance, params=params)
            except RuntimeError:
                out = self._request("GET", "/rest/api/3/search", instance, params=params)
            return ToolResult(success=True, data={"issues": out.get("issues", [])})
        except RuntimeError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error searching JQL: {e}")

    def _status_entered_at(self, ticket_id: str, status_name: str, instance: str = "") -> ToolResult:
        """Get timestamp of the last transition into a given status.

        Useful for idempotency — the timestamp serves as a unique key for re-runs.

        Args:
            ticket_id: The Jira ticket ID.
            status_name: Status name to find the entry timestamp for.
            instance: Instance name override.

        Returns:
            ToolResult with entered_at timestamp string.
        """
        if not status_name:
            return ToolResult(success=False, error="Missing required parameter: status_name")

        try:
            out = self._request(
                "GET",
                f"/rest/api/3/issue/{ticket_id}/changelog",
                instance,
                params={"maxResults": 100},
            )
            entered = ""
            for h in out.get("values", []):
                for item in h.get("items", []):
                    if (item.get("field") == "status"
                            and (item.get("toString") or "").upper() == status_name.upper()):
                        entered = h.get("created", "")
            return ToolResult(success=True, data={"entered_at": entered})
        except RuntimeError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error getting status timestamp: {e}")
