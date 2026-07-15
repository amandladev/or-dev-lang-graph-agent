"""Publisher agent implementation.

Handles post-implementation publishing:
1. Reads project workflow rules from vault (branching, commit conventions, Jira transitions)
2. Creates branch, commits, and pushes according to rules
3. Updates Jira ticket status and adds work summary

Rules are loaded from a specific file (.autopilot-rules.md) in the vault,
with fallback to searching notes for relevant workflow information.
"""

import re
import subprocess
import os
from pathlib import Path
from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


# Default rules file name in the vault
RULES_FILENAME = ".autopilot-rules.md"

_DISALLOWED_RUN = re.compile(r"[^a-z0-9]+")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


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

        except Exception:
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

    @staticmethod
    def _sanitize_branch_slug(title: str) -> str:
        """Convert a ticket title into a safe branch-name slug.

        Lowercases the title, replaces any run of characters that are not
        lowercase ASCII letters or digits with a single hyphen, trims
        leading/trailing hyphens, falls back to "implementation" if the
        result is empty, and truncates to 30 Unicode code points.

        Args:
            title: Raw ticket title.

        Returns:
            A slug composed only of lowercase alphanumerics and hyphens,
            at most 30 code points long, never starting or ending with a
            hyphen, and never empty.
        """
        lowered = title.lower()
        collapsed = _DISALLOWED_RUN.sub("-", lowered)
        trimmed = collapsed.strip("-")
        slug = trimmed or "implementation"
        truncated = slug[:30]
        return truncated.rstrip("-") or "implementation"

    @staticmethod
    def _sanitize_commit_message(message: str) -> str:
        """Strip control characters and newlines from a commit message.

        Removes every character in U+0000-U+001F or U+007F (preserving
        spaces), and substitutes "Automated commit" if the result is
        empty or whitespace-only.

        Args:
            message: Raw, fully formatted commit message.

        Returns:
            A commit message with no control characters, never empty.
        """
        cleaned = _CONTROL_CHARS.sub("", message)
        return cleaned if cleaned.strip() else "Automated commit"

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

        title = ticket.get("title", "implementation")
        branch_slug = self._sanitize_branch_slug(title)
        branch_name = rules["branch_pattern"].format(
            ticket_id=ticket_id.lower(),
            description=branch_slug,
        )
        results["branch"] = branch_name

        # 1. Checkout source branch and pull
        source = rules["branch_from"]
        if not self._git_cmd(["checkout", source], results):
            return results
        if not self._git_cmd(["pull"], results):
            return results

        # 2. Create feature branch
        if not self._git_cmd(["checkout", "-b", branch_name], results):
            return results

        # 3. Stage all changes
        if not self._git_cmd(["add", "-A"], results):
            return results

        # 4. Commit with conventional message
        raw_commit_msg = rules["commit_pattern"].format(
            ticket_id=ticket_id,
            description=ticket.get("title", "Implementation"),
        )
        commit_message = self._sanitize_commit_message(raw_commit_msg)
        results["commit_message"] = commit_message
        if not self._git_cmd(["commit", "-m", commit_message], results):
            return results

        # 5. Push
        remote = rules["push_remote"]
        if not self._git_cmd(["push", "-u", remote, branch_name], results):
            return results

        return results

    def _git_cmd(self, args: list[str], results: dict) -> bool:
        """Execute a git command and log the result.

        Args:
            args: Git arguments as separate list elements (e.g.,
                ["checkout", "develop"]).
            results: Results dict to append operation log.

        Returns:
            True if command succeeded, False otherwise.
        """
        command = ["git", *args]
        try:
            result = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path.cwd()),
            )

            success = result.returncode == 0
            results["operations"].append({
                "command": command,
                "success": success,
                "output": result.stdout.strip() or result.stderr.strip(),
            })
            return success

        except Exception as e:
            results["operations"].append({
                "command": command,
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

        # Full Jira update API not yet implemented — report as skipped so
        # downstream metrics consumers don't mistake this for a real update.
        return {
            "skipped": True,
            "ticket_id": ticket_id,
            "transition": transition,
            "reason": "Jira update not yet implemented",
        }
