"""Publisher agent implementation.

Handles post-implementation publishing:
1. Reads project workflow rules from vault (branching, commit conventions, Jira transitions)
2. Creates branch, commits, and pushes according to rules
3. Updates Jira ticket status and adds work summary

Rules are loaded from a specific file (.autopilot-rules.md) in the vault,
with fallback to searching notes for relevant workflow information.
"""

import subprocess
import os
from pathlib import Path
from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


# Default rules file name in the vault
RULES_FILENAME = ".autopilot-rules.md"


class PublisherAgent:
    """Publishes results and updates ticket tracking systems.

    Reads workflow rules from the vault to determine:
    - Branch naming conventions
    - Commit message format
    - Source branch (qa, develop, main, etc.)
    - Jira status transitions
    - PR/review requirements

    Then executes the publishing workflow accordingly.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize PublisherAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        return "Publisher"

    @property
    def description(self) -> str:
        return "Publishes results and updates ticket tracking systems"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"evidence": list, "ticket": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"metrics": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the publishing workflow.

        1. Load workflow rules from vault
        2. Create branch from source (if rules specify)
        3. Stage and commit changes
        4. Push to remote
        5. Update Jira ticket (if rules specify)

        Args:
            state: Fields from WorkflowState. Expected: "evidence", "ticket".
            memory_context: Optional memory data (unused currently).

        Returns:
            Dict with "metrics" containing publishing results.
        """
        ticket = state.get("ticket", {})
        evidence = state.get("evidence", [])
        ticket_id = ticket.get("id", "unknown")

        # Step 1: Load workflow rules
        rules = self._load_rules()

        # Step 2: Git operations
        git_results = self._execute_git_workflow(ticket_id, ticket, rules)

        # Step 3: Update Jira (if configured)
        jira_result = self._update_jira(ticket_id, ticket, evidence, rules)

        metrics = {
            "published": True,
            "ticket_id": ticket_id,
            "git": git_results,
            "jira_update": jira_result,
            "rules_applied": rules.get("source", "default"),
        }

        return {"metrics": metrics}

    def _load_rules(self) -> dict[str, Any]:
        """Load workflow rules from vault.

        Tries to find rules in this order:
        1. .autopilot-rules.md in the vault root
        2. Search vault for "workflow" or "branching" notes
        3. Default rules

        Returns:
            Dict with workflow rules (branch_from, branch_pattern,
            commit_pattern, jira_transition, etc.)
        """
        # Try to read the dedicated rules file from vault
        try:
            obsidian = self._tool_registry.get("obsidian")

            # First try the dedicated rules file
            result = obsidian.execute(query=RULES_FILENAME)
            if result.success and result.data:
                for note in result.data:
                    if RULES_FILENAME in note.get("path", "") or RULES_FILENAME in note.get("title", ""):
                        return self._parse_rules(note.get("excerpt", ""))

            # Fallback: search for workflow/branching rules
            result = obsidian.execute(query="branching workflow rules commit convention")
            if result.success and result.data:
                # Use the highest-scoring result
                top_note = result.data[0] if result.data else {}
                excerpt = top_note.get("excerpt", "")
                if excerpt:
                    return self._parse_rules(excerpt)

        except (KeyError, Exception):
            pass

        # Default rules if nothing found
        return self._default_rules()

    def _parse_rules(self, content: str) -> dict[str, Any]:
        """Parse workflow rules from markdown content.

        Looks for key-value patterns in the content. Expected format:
        - branch_from: develop
        - branch_pattern: feature/{ticket_id}-{description}
        - commit_pattern: feat({ticket_id}): {description}
        - jira_transition: In Progress -> Code Review
        - push_remote: origin

        Args:
            content: Markdown content with rules.

        Returns:
            Parsed rules dict with defaults for missing fields.
        """
        rules = self._default_rules()
        rules["source"] = "vault"

        content_lower = content.lower()

        for line in content.split("\n"):
            stripped = line.strip().lstrip("- ")
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip().lower().replace(" ", "_")
                value = value.strip()

                if key in ("branch_from", "source_branch"):
                    rules["branch_from"] = value
                elif key in ("branch_pattern", "branch_format"):
                    rules["branch_pattern"] = value
                elif key in ("commit_pattern", "commit_format"):
                    rules["commit_pattern"] = value
                elif key in ("jira_transition", "jira_status"):
                    rules["jira_transition"] = value
                elif key in ("push_remote", "remote"):
                    rules["push_remote"] = value

        return rules

    def _default_rules(self) -> dict[str, Any]:
        """Return default workflow rules."""
        return {
            "source": "default",
            "branch_from": "develop",
            "branch_pattern": "feature/{ticket_id}",
            "commit_pattern": "feat({ticket_id}): {description}",
            "jira_transition": "",  # Don't transition if no rules found
            "push_remote": "origin",
        }

    def _execute_git_workflow(
        self, ticket_id: str, ticket: dict, rules: dict
    ) -> dict[str, Any]:
        """Execute the git workflow according to rules.

        Args:
            ticket_id: The ticket identifier.
            ticket: Full ticket data.
            rules: Workflow rules dict.

        Returns:
            Dict with git operation results.
        """
        results: dict[str, Any] = {"operations": []}

        # Format branch name
        description = ticket.get("title", "implementation").lower()
        description = description.replace(" ", "-")[:30]
        branch_name = rules["branch_pattern"].format(
            ticket_id=ticket_id.lower(),
            description=description,
        )

        # 1. Checkout source branch and pull
        source = rules["branch_from"]
        self._git_cmd(f"checkout {source}", results)
        self._git_cmd("pull", results)

        # 2. Create feature branch
        self._git_cmd(f"checkout -b {branch_name}", results)

        # 3. Stage all changes
        self._git_cmd("add -A", results)

        # 4. Commit with conventional message
        title = ticket.get("title", "Implementation")
        commit_msg = rules["commit_pattern"].format(
            ticket_id=ticket_id,
            description=title,
        )
        self._git_cmd(f'commit -m "{commit_msg}"', results)

        # 5. Push
        remote = rules["push_remote"]
        self._git_cmd(f"push -u {remote} {branch_name}", results)

        results["branch"] = branch_name
        results["commit_message"] = commit_msg

        return results

    def _git_cmd(self, args: str, results: dict) -> bool:
        """Execute a git command and log the result.

        Args:
            args: Git arguments (e.g., "checkout develop").
            results: Results dict to append operation log.

        Returns:
            True if command succeeded, False otherwise.
        """
        try:
            cmd = f"git {args}"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path.cwd()),
            )

            success = result.returncode == 0
            results["operations"].append({
                "command": cmd,
                "success": success,
                "output": result.stdout.strip() or result.stderr.strip(),
            })
            return success

        except (subprocess.TimeoutExpired, Exception) as e:
            results["operations"].append({
                "command": f"git {args}",
                "success": False,
                "output": str(e),
            })
            return False

    def _update_jira(
        self,
        ticket_id: str,
        ticket: dict,
        evidence: list,
        rules: dict,
    ) -> dict[str, Any]:
        """Update the Jira ticket status and add a comment.

        Args:
            ticket_id: The ticket identifier.
            ticket: Full ticket data.
            evidence: Test results and other evidence.
            rules: Workflow rules including transition info.

        Returns:
            Dict with Jira update results.
        """
        transition = rules.get("jira_transition", "")
        if not transition:
            return {"skipped": True, "reason": "No jira_transition rule configured"}

        # For now, log what would be done (full Jira update API TBD)
        return {
            "skipped": False,
            "ticket_id": ticket_id,
            "transition": transition,
            "note": "Jira status transition not yet implemented — would transition to: " + transition,
        }
