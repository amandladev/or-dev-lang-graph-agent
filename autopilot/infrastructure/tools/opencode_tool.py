"""OpenCode tool implementation — executes prompts via opencode CLI.

Uses `opencode run` in batch mode to send prompts and capture responses.
Supports model selection, session persistence, and working directory control.

Session management:
- First call creates a new session
- Subsequent calls use `--continue` to maintain context
- All agents in a workflow share the same OpenCode session
"""

import os
import subprocess
from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolResult


class OpenCodeTool:
    """Tool for executing prompts through OpenCode CLI.

    Wraps `opencode run` for non-interactive usage. Maintains a single
    session across multiple calls so OpenCode keeps context of files
    and changes throughout the workflow.
    """

    def __init__(self, model: str = "", timeout: int = 300) -> None:
        """Initialize OpenCodeTool.

        Args:
            model: Model to use in format "provider/model" (e.g., "anthropic/claude-sonnet-4-20250514").
                If empty, uses OpenCode's configured default.
            timeout: Maximum seconds to wait for opencode to complete.
        """
        self._model = model
        self._timeout = timeout
        self._session_active = False  # Tracks if we've started a session

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"prompt": str, "cwd": str, "model": str}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"result": str, "exit_code": int}

    @property
    def session_active(self) -> bool:
        """Whether a session has been started (subsequent calls will use --continue)."""
        return self._session_active

    def reset_session(self) -> None:
        """Reset session state. Next call will start a fresh session."""
        self._session_active = False

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a prompt through opencode run.

        First call starts a new session. All subsequent calls use --continue
        to maintain context within the same workflow execution.

        Args:
            prompt: The message/instruction to send to OpenCode.
            cwd: Working directory for the opencode process (default: current dir).
            model: Model override for this specific call (optional).

        Returns:
            ToolResult with OpenCode's output text and exit code.
        """
        prompt = kwargs.get("prompt", "")
        cwd = kwargs.get("cwd", "")
        model = kwargs.get("model", "") or self._model

        if not prompt:
            return ToolResult(success=False, error="Missing required parameter: prompt")

        # Build the command
        cmd = ["opencode", "run", prompt]

        if model:
            cmd.extend(["-m", model])

        # Continue the session if one is already active
        if self._session_active:
            cmd.append("--continue")

        # Set working directory
        work_dir = cwd if cwd else None

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=work_dir,
                env={**os.environ},
            )

            output = result.stdout.strip()
            if result.stderr:
                output += f"\n[stderr]: {result.stderr.strip()}"

            if result.returncode == 0:
                # Mark session as active after first successful call
                self._session_active = True
                return ToolResult(
                    success=True,
                    data={"result": output, "exit_code": 0},
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"OpenCode exited with code {result.returncode}: {output}",
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"OpenCode timed out after {self._timeout} seconds",
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error="opencode command not found. Is it installed and in PATH?",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Error running opencode: {e}")
