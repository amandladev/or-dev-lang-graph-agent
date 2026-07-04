"""OpenCode tool implementation — executes prompts via opencode CLI.

Uses `opencode run` in batch mode to send prompts and capture responses.
Supports model selection, session continuation, and working directory control.
"""

import subprocess
import os
from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult


class OpenCodeTool:
    """Tool for executing prompts through OpenCode CLI.

    Wraps `opencode run` for non-interactive usage. Agents provide
    a prompt describing the desired code change, and OpenCode executes it.
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

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"prompt": str, "cwd": str, "session": str, "model": str}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"result": str, "exit_code": int}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a prompt through opencode run.

        Args:
            prompt: The message/instruction to send to OpenCode.
            cwd: Working directory for the opencode process (default: current dir).
            session: Session ID to continue (optional).
            model: Model override for this specific call (optional).

        Returns:
            ToolResult with OpenCode's output text and exit code.
        """
        prompt = kwargs.get("prompt", "")
        cwd = kwargs.get("cwd", "")
        session = kwargs.get("session", "")
        model = kwargs.get("model", "") or self._model

        if not prompt:
            return ToolResult(success=False, error="Missing required parameter: prompt")

        # Build the command
        cmd = ["opencode", "run", prompt]

        if model:
            cmd.extend(["-m", model])

        if session:
            cmd.extend(["-s", session])

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
