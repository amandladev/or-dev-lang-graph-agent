"""Workflow branch and publishing rules loaded from the knowledge vault."""

from typing import Any

from autopilot.application.registries.tool_registry import ToolRegistry


RULES_FILENAME = ".autopilot-rules.md"


class WorkflowRulesProvider:
    """Loads the rules shared by workspace creation and publishing."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry

    def load(self) -> dict[str, Any]:
        """Load vault rules, falling back to safe defaults."""
        try:
            obsidian = self._tool_registry.get("obsidian")
            result = obsidian.execute(query=RULES_FILENAME)
            if result.success and result.data:
                for note in result.data:
                    if RULES_FILENAME in note.get("path", "") or RULES_FILENAME in note.get("title", ""):
                        return self.parse(note.get("excerpt", ""))

            result = obsidian.execute(query="branching workflow rules commit convention")
            if result.success and result.data:
                excerpt = result.data[0].get("excerpt", "")
                if excerpt:
                    return self.parse(excerpt)
        except Exception:
            pass
        return self.defaults()

    def parse(self, content: str) -> dict[str, Any]:
        """Parse key-value workflow rules from markdown."""
        rules = self.defaults()
        rules["source"] = "vault"
        for line in content.split("\n"):
            stripped = line.strip().lstrip("- ")
            if ":" not in stripped:
                continue
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

    def defaults(self) -> dict[str, Any]:
        """Return default publishing rules."""
        return {
            "source": "default",
            "branch_from": "develop",
            "branch_pattern": "feature/{ticket_id}",
            "commit_pattern": "feat({ticket_id}): {description}",
            "jira_transition": "",
            "push_remote": "origin",
        }
