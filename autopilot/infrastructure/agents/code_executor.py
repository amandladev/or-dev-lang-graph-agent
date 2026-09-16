"""Code Executor agent implementation.

Executes implementation plan steps through OpenCode. Each step from the
Planner becomes a prompt sent to OpenCode, which performs the actual
code modifications.
"""

import subprocess
from pathlib import Path
from typing import Any

from autopilot.application.registries.tool_registry import ToolRegistry
from autopilot.domain.value_objects.exceptions import CodeExecutionVerificationError


class CodeExecutorAgent:
    """Executes code changes based on the implementation plan.

    Iterates through the plan steps and delegates each one to OpenCode.
    Tracks modified files and reports results.
    """

    def __init__(self, tool_registry: ToolRegistry, logger=None) -> None:
        """Initialize CodeExecutorAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
            logger: Optional StructuredLogger for per-step progress output.
        """
        self._tool_registry = tool_registry
        self._logger = logger

    @property
    def name(self) -> str:
        return "Code_Executor"

    @property
    def description(self) -> str:
        return "Executes code changes based on the implementation plan"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"plan": dict, "context": dict, "workspace": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"modified_files": list, "evidence": list}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute code changes according to the plan.

        Sends each plan step to OpenCode as a prompt. OpenCode performs
        the actual file modifications in the current workspace.

        Args:
            state: Fields from WorkflowState. Expected: "plan", "context".
            memory_context: Optional memory data (unused currently).

        Returns:
            Dict with "modified_files" list of changed file paths.
        """
        plan = state.get("plan", {})
        context = state.get("context", {})
        workspace = state.get("workspace", {})
        workspace_path = workspace.get("path", "") if isinstance(workspace, dict) else ""
        steps = plan.get("steps", [])

        if not steps:
            return {"modified_files": []}

        try:
            opencode = self._tool_registry.get("opencode")
        except KeyError:
            raise RuntimeError("OpenCode tool not available in registry")

        modified_files: list[str] = []
        execution_log: list[dict] = []

        for step in steps:
            step_num = step.get("step", 0)
            description = step.get("description", "")
            total_steps = len(steps)

            if not description:
                continue

            # Build execution prompt with context
            prompt = self._build_execution_prompt(step, plan, context)

            # Report progress before delegating to OpenCode
            short = " ".join(description.split())[:80]
            if self._logger is not None and hasattr(self._logger, "log_agent_progress"):
                self._logger.log_agent_progress(
                    "Code_Executor", f"step {step_num}/{total_steps}: {short}"
                )

            # Execute via OpenCode
            result = opencode.execute(prompt=prompt, cwd=workspace_path)

            step_result = {
                "step": step_num,
                "description": description,
                "success": result.success,
            }

            if result.success:
                output = result.data.get("result", "") if result.data else ""
                step_result["output"] = output
                # Try to extract modified files from OpenCode's output
                files = self._extract_modified_files(output)
                modified_files.extend(files)
            else:
                step_result["error"] = result.error
                # Don't stop on individual step failure — log and continue
                # The Tester will catch issues

            execution_log.append(step_result)

        evidence = [{
            "type": "execution_log",
            "description": f"Code_Executor ran {len(execution_log)} plan step(s)",
            "data": {"steps": execution_log},
        }]

        # Prefer the ground-truth list of files actually changed in the
        # working tree over the free-text heuristic, which is likely to
        # under- or over-report depending on OpenCode's exact output format.
        git_files = self._git_modified_files(workspace_path or None)
        if git_files is not None:
            modified_files = git_files
        else:
            modified_files = list(set(modified_files))

        self._verify_expected_files(plan, workspace_path, modified_files)

        return {
            "modified_files": modified_files,
            "evidence": evidence,
        }

    def _verify_expected_files(
        self, plan: dict, workspace_path: str, modified_files: list[str]
    ) -> None:
        """Fail loudly if none of the plan's expected files landed in the workspace.

        OpenCode runs as an external process; its own project/session
        resolution can attach to a different directory than the one passed
        via subprocess cwd and silently write there instead. When that
        happens, `workspace_path` ends up with no real changes (at most the
        engine's own state file), and every downstream agent would report a
        false PASS on an effectively empty commit. Checking that at least
        one expected file actually exists catches that failure mode without
        flagging a legitimate partial implementation (where the Tester is
        the right place to fail on incomplete work).

        Args:
            plan: The plan dict, optionally containing "expected_files".
            workspace_path: The ticket's worktree path, if any.
            modified_files: Ground-truth changed files from `git status`.
        """
        expected_files = plan.get("expected_files", []) if isinstance(plan, dict) else []
        if not expected_files or not workspace_path:
            return

        base = Path(workspace_path)
        found = any(
            f in modified_files or (base / f).exists() for f in expected_files
        )
        if not found:
            raise CodeExecutionVerificationError(
                "None of the plan's expected files "
                f"({expected_files}) were found in the workspace after "
                f"execution ({workspace_path}); only {modified_files or 'no files'} "
                "changed. OpenCode's changes likely landed outside this "
                "workspace — check for a stale `opencode` session/server "
                "attached to a different project directory."
            )

    def _build_execution_prompt(self, step: dict, plan: dict, context: dict) -> str:
        """Build the execution prompt for a single plan step.

        Args:
            step: The current step dict.
            plan: The full plan for context.
            context: Assembled context from ContextBuilder.

        Returns:
            Formatted prompt string for OpenCode.
        """
        step_num = step.get("step", 0)
        description = step.get("description", "")
        total_steps = len(plan.get("steps", []))
        ticket_id = plan.get("ticket_id", "")

        prompt = f"""Execute step {step_num}/{total_steps} for ticket {ticket_id}:

{description}

Important:
- Make the minimal changes needed
- Follow existing code style and patterns
- Don't break existing functionality
- Do NOT run any git commands (checkout, branch, commit, push, pull, rebase,
  reset, merge). Autopilot handles version control automatically; only write
  or modify files.
"""
        return prompt.strip()

    def _extract_modified_files(self, output: str) -> list[str]:
        """Try to extract file paths from OpenCode's output.

        Looks for common patterns that indicate file modifications
        (e.g., "Modified: src/file.py", file paths in output).

        Args:
            output: Raw output from OpenCode.

        Returns:
            List of file paths that were likely modified.
        """
        files = []
        for line in output.split("\n"):
            stripped = line.strip()
            # Look for file modification indicators
            for prefix in ("Modified:", "Created:", "Updated:", "Wrote:", "✓"):
                if stripped.startswith(prefix):
                    path = stripped[len(prefix):].strip()
                    if path and "/" in path or "." in path:
                        files.append(path)
                        break
        return files

    def _git_modified_files(self, cwd: str | Path | None = None) -> list[str] | None:
        """Get the list of files actually changed in the working tree via git.

        Uses `git status --porcelain` as the ground truth for what OpenCode
        modified, since parsing its free-text stdout is brittle. Covers
        staged, unstaged, and untracked files, and correctly handles
        renames (reports the new path).

        Returns:
            Sorted list of relative file paths changed in the working tree,
            or None if the current directory is not a git repository (or
            the command otherwise fails), so callers can fall back to the
            text-heuristic result.
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(cwd or Path.cwd()),
            )
        except Exception:
            return None

        if result.returncode != 0:
            return None

        files: set[str] = set()
        for line in result.stdout.splitlines():
            if not line or len(line) < 4:
                continue
            path_part = line[3:]
            # Renames are reported as "old -> new"; keep the new path.
            if " -> " in path_part:
                path_part = path_part.split(" -> ", 1)[1]
            path_part = path_part.strip().strip('"')
            if path_part:
                files.add(path_part)

        return sorted(files)
