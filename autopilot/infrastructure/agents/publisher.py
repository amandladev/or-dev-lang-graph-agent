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
from pathlib import Path
from typing import Any

from autopilot.application.registries.tool_registry import ToolRegistry
from autopilot.domain.value_objects.exceptions import PublishError
from autopilot.infrastructure.adapters.workflow_rules import WorkflowRulesProvider

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

    def __init__(self, tool_registry: ToolRegistry, rules_provider=None) -> None:
        """Initialize PublisherAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry
        self._rules_provider = rules_provider or WorkflowRulesProvider(tool_registry)

    @property
    def name(self) -> str:
        return "Publisher"

    @property
    def description(self) -> str:
        return "Publishes results and updates ticket tracking systems"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"evidence": list, "ticket": dict, "modified_files": list, "workspace": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"metrics": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: dict[str, Any] | None = None,
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
        modified_files = state.get("modified_files", [])
        workspace = state.get("workspace", {})
        ticket_id = ticket.get("id", "unknown")

        metadata = memory_context or {}
        if metadata.get("mode") == "dry-run":
            return {
                "metrics": {
                    "published": False,
                    "dry_run": True,
                    "ticket_id": ticket_id,
                    "git": {"operations": [], "skipped": True},
                    "jira_update": {"skipped": True, "reason": "dry-run mode"},
                    "rules_applied": "none",
                }
            }

        rules = self._load_rules()

        git_results = self._execute_git_workflow(ticket_id, ticket, rules, workspace, modified_files)

        jira_result = self._update_jira(ticket_id, ticket, evidence, rules)

        metrics = {
            "published": all(op["success"] for op in git_results["operations"]),
            "ticket_id": ticket_id,
            "git": git_results,
            "jira_update": jira_result,
            "rules_applied": rules.get("source", "default"),
        }

        if not metrics["published"]:
            failed = [op for op in git_results["operations"] if not op["success"]]
            details = "; ".join(
                f"{' '.join(op['command'])} -> {op['output'][:200]}" for op in failed
            )
            raise PublishError(f"Git workflow failed: {details}")

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
        return self._rules_provider.load()

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
        return self._rules_provider.parse(content)

    def _default_rules(self) -> dict[str, Any]:
        """Return default workflow rules."""
        return self._rules_provider.defaults()

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
        self,
        ticket_id: str,
        ticket: dict,
        rules: dict,
        workspace: dict | None = None,
        modified_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute the git workflow according to rules.

        Args:
            ticket_id: The ticket identifier.
            ticket: Full ticket data.
            rules: Workflow rules dict.

        Returns:
            Dict with git operation results.
        """
        if workspace and workspace.get("path"):
            return self._execute_workspace_git_workflow(
                ticket_id, ticket, rules, workspace, modified_files or []
            )

        results: dict[str, Any] = {"operations": []}

        title = ticket.get("title", "implementation")
        branch_slug = self._sanitize_branch_slug(title)
        branch_name = rules["branch_pattern"].format(
            ticket_id=ticket_id.lower(),
            description=branch_slug,
        )
        results["branch"] = branch_name

        source = rules["branch_from"]
        if not self._git_cmd(["checkout", source], results):
            return results
        if not self._git_cmd(["pull"], results):
            return results

        if not self._git_cmd(["checkout", "-b", branch_name], results):
            return results

        if not self._git_cmd(["add", "-A"], results):
            return results

        raw_commit_msg = rules["commit_pattern"].format(
            ticket_id=ticket_id,
            description=ticket.get("title", "Implementation"),
        )
        commit_message = self._sanitize_commit_message(raw_commit_msg)
        results["commit_message"] = commit_message
        if not self._git_cmd(["commit", "-m", commit_message], results):
            return results

        remote = rules["push_remote"]
        if not self._git_cmd(["push", "-u", remote, branch_name], results):
            return results

        return results

    def _execute_workspace_git_workflow(
        self,
        ticket_id: str,
        ticket: dict,
        rules: dict,
        workspace: dict,
        modified_files: list[str],
    ) -> dict[str, Any]:
        """Commit and push only the branch-owned worktree."""
        results: dict[str, Any] = {
            "operations": [],
            "branch": workspace.get("branch", ""),
            "workspace": workspace.get("path", ""),
        }
        cwd = workspace["path"]
        expected_branch = workspace["branch"]
        if not self._validate_workspace(cwd, expected_branch, results):
            return results

        files = modified_files or self._status_files(cwd)
        if not files:
            results["operations"].append({
                "command": ["git", "status", "--porcelain"],
                "success": False,
                "output": "No ticket changes found to commit",
            })
            return results

        if not self._git_cmd(["add", "--", *files], results, cwd=cwd):
            return results

        raw_commit_msg = rules.get("commit_pattern", "feat({ticket_id}): {description}").format(
            ticket_id=ticket_id,
            description=ticket.get("title", "Implementation"),
        )
        commit_message = self._sanitize_commit_message(raw_commit_msg)
        results["commit_message"] = commit_message
        if not self._git_cmd(["commit", "-m", commit_message], results, cwd=cwd):
            return results

        remote = rules.get("push_remote", "origin")
        if not self._git_cmd(["remote", "get-url", remote], results, cwd=cwd):
            return results
        self._git_cmd(["push", "-u", remote, expected_branch], results, cwd=cwd)
        return results

    def _validate_workspace(self, cwd: str, expected_branch: str, results: dict) -> bool:
        branch_result = self._git_cmd_result(["branch", "--show-current"], cwd)
        root_result = self._git_cmd_result(["rev-parse", "--show-toplevel"], cwd)
        valid = (
            branch_result.returncode == 0
            and root_result.returncode == 0
            and branch_result.stdout.strip() == expected_branch
            and Path(root_result.stdout.strip()).resolve() == Path(cwd).resolve()
        )
        if not valid:
            results["operations"].append({
                "command": ["git", "workspace-validate", cwd, expected_branch],
                "success": False,
                "output": "Workspace path or branch does not match expected ticket metadata",
            })
        return valid

    def _status_files(self, cwd: str) -> list[str]:
        result = self._git_cmd_result(["status", "--porcelain", "--untracked-files=all"], cwd)
        if result.returncode != 0:
            return []
        files = []
        for line in result.stdout.splitlines():
            if len(line) >= 4:
                path = line[3:].split(" -> ", 1)[-1].strip().strip('"')
                if path:
                    files.append(path)
        return sorted(set(files))

    def _git_cmd(self, args: list[str], results: dict, cwd: str | None = None) -> bool:
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
                cwd=cwd or str(Path.cwd()),
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

    def _git_cmd_result(self, args: list[str], cwd: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )

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
