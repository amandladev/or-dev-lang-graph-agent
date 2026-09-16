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
import sys
import threading
from pathlib import Path
from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolResult


class OpenCodeTool:
    """Tool for executing prompts through OpenCode CLI.

    Wraps `opencode run` for non-interactive usage. Maintains a single
    session across multiple calls so OpenCode keeps context of files
    and changes throughout the workflow.
    """

    def __init__(
        self,
        model: str = "",
        timeout: int = 300,
        stream_output: bool = False,
    ) -> None:
        """Initialize OpenCodeTool.

        Args:
            model: Model to use in format "provider/model" (e.g., "anthropic/claude-sonnet-4-20250514").
                If empty, uses OpenCode's configured default.
            timeout: Maximum seconds to wait for opencode to complete.
            stream_output: When True, streams opencode's stdout/stderr lines
                live to the terminal instead of capturing them silently.
        """
        self._model = model
        self._timeout = timeout
        self._stream_output = stream_output
        self._session_active_by_cwd: dict[str, bool] = {}
        self._session_lock = threading.Lock()

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
        return any(self._session_active_by_cwd.values())

    def reset_session(self) -> None:
        """Reset session state. Next call will start a fresh session."""
        with self._session_lock:
            self._session_active_by_cwd.clear()

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

        session_key = self._session_key(cwd)
        with self._session_lock:
            session_active = self._session_active_by_cwd.get(session_key, False)

        # Continue only the session associated with this workspace.
        if session_active:
            cmd.append("--continue")

        # Set working directory
        work_dir = cwd if cwd else None
        if work_dir:
            cmd.extend(["--dir", work_dir])

        try:
            if self._stream_output:
                return self._run_streaming(cmd, work_dir)

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
                with self._session_lock:
                    self._session_active_by_cwd[session_key] = True
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
                error="opencode command not found. Is it installed in PATH?",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Error running opencode: {e}")

    def _run_streaming(self, cmd: list[str], work_dir: str | None) -> ToolResult:
        """Run opencode streaming its output live to the terminal.

        stdout lines are printed to stdout and stderr lines to stderr as
        they arrive, while still capturing the full output for the result.

        Args:
            cmd: The command list to execute.
            work_dir: Working directory for the process, or None.

        Returns:
            ToolResult with OpenCode's captured output and exit code.
        """
        stdout_sink: list[str] = []
        stderr_sink: list[str] = []
        session_key = self._session_key(work_dir or "")

        def _pump(stream, sink, to_stderr: bool) -> None:
            for line in stream:
                print(line, end="", flush=True, file=sys.stderr if to_stderr else sys.stdout)
                sink.append(line)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=work_dir,
            env={**os.environ},
        )

        t_out = threading.Thread(
            target=_pump, args=(proc.stdout, stdout_sink, False), daemon=True
        )
        t_err = threading.Thread(
            target=_pump, args=(proc.stderr, stderr_sink, True), daemon=True
        )
        t_out.start()
        t_err.start()

        try:
            proc.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return ToolResult(
                success=False,
                error=f"OpenCode timed out after {self._timeout} seconds",
            )

        t_out.join(timeout=5)
        t_err.join(timeout=5)

        output = "".join(stdout_sink).strip()
        if stderr_sink:
            output += "\n[stderr]: " + "".join(stderr_sink).strip()

        if proc.returncode == 0:
            with self._session_lock:
                self._session_active_by_cwd[session_key] = True
            return ToolResult(
                success=True,
                data={"result": output, "exit_code": 0},
            )
        return ToolResult(
            success=False,
            error=f"OpenCode exited with code {proc.returncode}: {output}",
        )

    @staticmethod
    def _session_key(cwd: str) -> str:
        """Build a stable session key for one physical workspace."""
        return str(Path(cwd).expanduser().resolve()) if cwd else str(Path.cwd().resolve())
