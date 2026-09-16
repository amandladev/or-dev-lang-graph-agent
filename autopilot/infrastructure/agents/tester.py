"""Tester agent implementation.

Detects the project type (Node.js/Python/etc.) and runs the appropriate
test suite. Reports results as evidence for the Publisher.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

from autopilot.application.registries.tool_registry import ToolRegistry


class TesterAgent:
    """Runs tests against modified files and produces evidence.

    Auto-detects the project type from config files (package.json,
    pyproject.toml, etc.) and runs the appropriate test command.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Initialize TesterAgent with tool registry.

        Args:
            tool_registry: Registry for accessing tools by name.
        """
        self._tool_registry = tool_registry

    @property
    def name(self) -> str:
        return "Tester"

    @property
    def description(self) -> str:
        return "Runs tests against modified files and produces evidence"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"modified_files": list, "workspace": dict}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"evidence": list}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the test suite and report results.

        Detects project type, runs tests, and returns evidence
        (pass/fail status, output, duration).

        Args:
            state: Fields from WorkflowState. Expected: "modified_files".
            memory_context: Optional memory data (unused currently).

        Returns:
            Dict with "evidence" list containing test results.
        """
        modified_files = state.get("modified_files", [])
        workspace = state.get("workspace", {})
        workspace_path = workspace.get("path", "") if isinstance(workspace, dict) else ""

        test_config = self._detect_test_config(workspace_path or None)
        metadata = dict(memory_context or {})
        metadata["test_attempts"] = int(metadata.get("test_attempts", 0)) + 1

        if not test_config:
            metadata["test_status"] = "skipped"
            return {
                "evidence": [{
                    "type": "test_result",
                    "description": "No test framework detected",
                    "data": {"status": "skipped", "reason": "No package.json or pyproject.toml found"},
                }],
                "metadata": metadata,
            }

        result = self._run_tests(test_config, workspace_path or None)

        evidence = [{
            "type": "test_result",
            "description": f"Test suite: {test_config['framework']}",
            "data": {
                "status": "passed" if result["success"] else "failed",
                "command": test_config["command"],
                "exit_code": result["exit_code"],
                "output": result["output"][-2000:],  # Truncate long output
                "modified_files": modified_files,
            },
        }]

        metadata["test_status"] = "passed" if result["success"] else "failed"
        return {"evidence": evidence, "metadata": metadata}

    def _detect_test_config(self, cwd: str | Path | None = None) -> dict[str, str] | None:
        """Detect the test framework and command from project files.

        Checks for common project config files in the current directory.

        Returns:
            Dict with "framework" and "command" keys, or None if not detected.
        """
        cwd = Path(cwd) if cwd else Path.cwd()

        package_json = cwd / "package.json"
        if package_json.exists():
            return self._parse_node_test_config(package_json)

        pyproject = cwd / "pyproject.toml"
        if pyproject.exists():
            return {"framework": "pytest", "command": "python3 -m pytest --tb=short"}

        setup_py = cwd / "setup.py"
        if setup_py.exists():
            return {"framework": "pytest", "command": "python3 -m pytest --tb=short"}

        makefile = cwd / "Makefile"
        if makefile.exists():
            content = makefile.read_text(encoding="utf-8", errors="ignore")
            if "test:" in content:
                return {"framework": "make", "command": "make test"}

        if self._has_python_tests(cwd):
            return {"framework": "pytest", "command": "python3 -m pytest --tb=short"}

        return None

    def _has_python_tests(self, cwd: Path) -> bool:
        """Check for pytest-style test files in the working directory."""
        if (cwd / "tests").is_dir():
            return any((cwd / "tests").glob("test_*.py")) or any(
                (cwd / "tests").glob("*_test.py")
            )
        return bool(list(cwd.glob("test_*.py")) + list(cwd.glob("*_test.py")))

    def _parse_node_test_config(self, package_json: Path) -> dict[str, str]:
        """Parse test command from package.json.

        Args:
            package_json: Path to package.json.

        Returns:
            Dict with framework and command.
        """
        import json

        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})

            # Prefer specific test commands
            if "test" in scripts:
                test_cmd = scripts["test"]
                if "jest" in test_cmd:
                    framework = "jest"
                elif "mocha" in test_cmd:
                    framework = "mocha"
                elif "vitest" in test_cmd:
                    framework = "vitest"
                else:
                    framework = "npm-test"
                return {"framework": framework, "command": "npm test"}

            # Fallback: check for test runner in devDependencies
            dev_deps = data.get("devDependencies", {})
            if "jest" in dev_deps:
                return {"framework": "jest", "command": "npx jest"}
            if "mocha" in dev_deps:
                return {"framework": "mocha", "command": "npx mocha"}
            if "vitest" in dev_deps:
                return {"framework": "vitest", "command": "npx vitest run"}

        except (json.JSONDecodeError, OSError):
            pass

        return {"framework": "npm-test", "command": "npm test"}

    def _run_tests(self, test_config: dict[str, str], cwd: str | Path | None = None) -> dict[str, Any]:
        """Execute the test command.

        Args:
            test_config: Dict with "command" key.

        Returns:
            Dict with success, exit_code, and output.
        """
        command = test_config["command"]

        try:
            result = subprocess.run(
                command.split(),
                capture_output=True,
                text=True,
                timeout=180,  # 3 minutes max for tests
                cwd=str(cwd or Path.cwd()),
                env={**os.environ},
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "output": output.strip(),
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "exit_code": -1,
                "output": "Test execution timed out after 180 seconds",
            }
        except FileNotFoundError as e:
            return {
                "success": False,
                "exit_code": -1,
                "output": f"Test command not found: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "output": f"Error running tests: {e}",
            }
