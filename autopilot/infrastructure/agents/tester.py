"""Tester agent implementation.

Detects the project type (Node.js/Python/etc.) and runs the appropriate
test suite. Reports results as evidence for the Publisher.
"""

import subprocess
import os
from pathlib import Path
from typing import Any, Optional

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
        return {"modified_files": list}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"evidence": list}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
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

        # Detect project type and test command
        test_config = self._detect_test_config()

        if not test_config:
            return {
                "evidence": [{
                    "type": "test_result",
                    "description": "No test framework detected",
                    "data": {"status": "skipped", "reason": "No package.json or pyproject.toml found"},
                }]
            }

        # Run the tests
        result = self._run_tests(test_config)

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

        # If tests failed, raise to trigger retry logic
        if not result["success"]:
            from autopilot.domain.value_objects.exceptions import TestFailureError
            raise TestFailureError(
                f"Tests failed (exit code {result['exit_code']}): "
                f"{result['output'][-500:]}"
            )

        return {"evidence": evidence}

    def _detect_test_config(self) -> dict[str, str] | None:
        """Detect the test framework and command from project files.

        Checks for common project config files in the current directory.

        Returns:
            Dict with "framework" and "command" keys, or None if not detected.
        """
        cwd = Path.cwd()

        # Check for Node.js project
        package_json = cwd / "package.json"
        if package_json.exists():
            return self._parse_node_test_config(package_json)

        # Check for Python project
        pyproject = cwd / "pyproject.toml"
        if pyproject.exists():
            return {"framework": "pytest", "command": "python3 -m pytest --tb=short"}

        # Check for setup.py (older Python)
        setup_py = cwd / "setup.py"
        if setup_py.exists():
            return {"framework": "pytest", "command": "python3 -m pytest --tb=short"}

        # Check for Makefile with test target
        makefile = cwd / "Makefile"
        if makefile.exists():
            content = makefile.read_text(encoding="utf-8", errors="ignore")
            if "test:" in content:
                return {"framework": "make", "command": "make test"}

        return None

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

    def _run_tests(self, test_config: dict[str, str]) -> dict[str, Any]:
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
                cwd=str(Path.cwd()),
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
