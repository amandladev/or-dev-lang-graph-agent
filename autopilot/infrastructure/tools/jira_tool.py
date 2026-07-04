"""Jira tool implementation for fetching ticket details via REST API.

Supports multiple Jira instances configured via environment variables:
- JIRA_<INSTANCE>_URL: Base URL (e.g., https://company.atlassian.net)
- JIRA_<INSTANCE>_EMAIL: Account email
- JIRA_<INSTANCE>_TOKEN: API token

The instance is inferred from the ticket ID prefix or can be specified explicitly.
"""

import os
import urllib.request
import urllib.error
import base64
import json
from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult


# Default Jira instance env var patterns
_DEFAULT_INSTANCE_VARS = {
    "url": "JIRA_{instance}_URL",
    "email": "JIRA_{instance}_EMAIL",
    "token": "JIRA_{instance}_TOKEN",
}


class JiraTool:
    """Tool for fetching Jira ticket details via REST API.

    Supports multiple Jira instances. Credentials are loaded from
    environment variables following the pattern JIRA_<INSTANCE>_<FIELD>.

    Actions:
        - "get_ticket": Fetch ticket details by ID
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
        return {"action": str, "ticket_id": str, "instance": str}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"ticket": dict}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a Jira operation.

        Args:
            action: The operation to perform ("get_ticket").
            ticket_id: The Jira ticket ID (e.g., "PROJ-123").
            instance: Optional Jira instance name override.

        Returns:
            ToolResult with ticket data on success, error description on failure.
        """
        action = kwargs.get("action", "get_ticket")
        ticket_id = kwargs.get("ticket_id", "")
        instance = kwargs.get("instance", "")

        if not ticket_id:
            return ToolResult(success=False, error="Missing required parameter: ticket_id")

        if action == "get_ticket":
            return self._get_ticket(ticket_id, instance)
        else:
            return ToolResult(success=False, error=f"Unsupported action: {action}")

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
