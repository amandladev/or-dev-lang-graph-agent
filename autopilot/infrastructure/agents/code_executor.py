"""Code Executor agent implementation.

Executes implementation plan steps through OpenCode. Each step from the
Planner becomes a prompt sent to OpenCode, which performs the actual
code modifications.
"""

from typing import Any, Optional

from autopilot.application.registries.tool_registry import ToolRegistry


class CodeExecutorAgent:
    """Executes code changes based on the implementation plan.

    Iterates through the plan steps and delegates each one to OpenCode.
    Tracks modified files and reports results.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize CodeExecutorAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        return "Code_Executor"

    @property
    def description(self) -> str:
        return "Executes code changes based on the implementation plan"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"plan": dict, "context": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"modified_files": list, "evidence": list}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
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

            if not description:
                continue

            # Build execution prompt with context
            prompt = self._build_execution_prompt(step, plan, context)

            # Execute via OpenCode
            result = opencode.execute(prompt=prompt)

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

        return {
            "modified_files": list(set(modified_files)),  # deduplicate
            "evidence": evidence,
        }

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
