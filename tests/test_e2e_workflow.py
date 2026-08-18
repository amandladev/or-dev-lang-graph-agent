"""End-to-end integration tests for the full Autopilot workflow.

Runs the complete pipeline (Context_Builder → Planner → Code_Executor →
Tester → Publisher → Documentation) with real agents, real git operations
and fake external tools (Jira, Obsidian, OpenCode) registered in the
shared ToolRegistry. Exercises the same path as `autopilot work TICKET-ID`.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from autopilot.cli.commands import cli
from autopilot.domain.interfaces.tool_interface import ToolResult
from autopilot.infrastructure.bootstrap import create_application

RULES_FILENAME = ".autopilot-rules.md"

FEATURE_SRC = 'def feature():\n    return "implemented"\n'
FEATURE_TEST = (
    "from src.feature import feature\n"
    "\n"
    "\n"
    "def test_feature():\n"
    '    assert feature() == "implemented"\n'
)


class FakeJiraTool:
    name = "jira"
    input_schema = {"action": str, "ticket_id": str}
    output_schema = {"result": dict}

    def __init__(self, ticket_data: dict | None = None) -> None:
        self.ticket_data = ticket_data or {
            "id": "TEST-1",
            "title": "Implement feature X",
            "description": "Implement a new feature described in the ticket.",
            "status": "In Progress",
            "project": "TEST",
            "labels": ["backend", "feature"],
            "comments": [{"author": "tester", "body": "Please implement"}],
        }
        self.calls: list[dict] = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        action = kwargs.get("action")
        if action == "get_ticket":
            return ToolResult(success=True, data=self.ticket_data)
        if action == "get_transitions":
            return ToolResult(success=True, data=[{"name": "Code Review"}])
        return ToolResult(success=True, data={})


class FakeObsidianTool:
    name = "obsidian"
    input_schema = {"query": str, "max_results": int}
    output_schema = {"notes": list}

    def __init__(self, vault_dir: Path) -> None:
        self.vault_dir = Path(vault_dir)
        self.calls: list[dict] = []

    def execute(self, query: str = "", max_results: int = 10, **kwargs):
        self.calls.append({"query": query, "max_results": max_results})
        if RULES_FILENAME in query:
            rules = self.vault_dir / RULES_FILENAME
            if rules.exists():
                return ToolResult(success=True, data=[{
                    "title": RULES_FILENAME,
                    "path": str(rules),
                    "excerpt": rules.read_text(encoding="utf-8"),
                }])
            return ToolResult(success=True, data=[])

        terms = [t.lower() for t in query.split() if len(t) > 2]
        notes = []
        for md in sorted(self.vault_dir.rglob("*.md")):
            if md.name == RULES_FILENAME:
                continue
            content = md.read_text(encoding="utf-8")
            if terms and not all(t in content.lower() or t in md.stem.lower() for t in terms):
                continue
            notes.append({
                "title": md.stem,
                "path": str(md),
                "excerpt": content[:300],
            })
            if len(notes) >= max_results:
                break
        return ToolResult(success=True, data=notes)


class FakeOpenCodeTool:
    name = "opencode"
    input_schema = {"prompt": str}
    output_schema = {"result": str}

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)
        self.calls: list[str] = []

    def execute(self, prompt: str = "", **kwargs):
        self.calls.append(prompt)
        if "implementation plan" in prompt.lower():
            return ToolResult(success=True, data={"result": (
                "1. Create src/feature.py with the feature logic\n"
                "2. Add tests/test_feature.py covering the feature\n"
            )})
        if "execute step" in prompt.lower():
            self._write_feature_files()
            return ToolResult(
                success=True,
                data={"result": "Modified: src/feature.py\nCreated: tests/test_feature.py"},
            )
        return ToolResult(success=True, data={"result": "ok"})

    def _write_feature_files(self) -> None:
        src = self.workdir / "src"
        src.mkdir(exist_ok=True)
        (src / "feature.py").write_text(FEATURE_SRC, encoding="utf-8")
        tests = self.workdir / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_feature.py").write_text(FEATURE_TEST, encoding="utf-8")


@pytest.fixture
def e2e_sandbox(tmp_path):
    workspace = tmp_path / "workspace"
    vault = tmp_path / "vault"
    remote = tmp_path / "remote.git"

    workspace.mkdir()
    vault.mkdir()
    subprocess.run(["git", "init", "-b", "develop"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=workspace, check=True, capture_output=True)
    (workspace / "README.md").write_text("# Sandbox workspace\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "develop"], cwd=workspace, check=True, capture_output=True)

    (vault / "feature-notes.md").write_text(
        "# Feature Notes\n\nImplement feature backend notes for the TEST project. "
        "Follow the existing conventions.\n",
        encoding="utf-8",
    )

    (workspace / "pyproject.toml").write_text(
        "[project]\n"
        'name = "sandbox"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.11"\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        'pythonpath = ["."]\n',
        encoding="utf-8",
    )

    config_file = tmp_path / "e2e.yaml"
    config_file.write_text(
        f'vault_location: "{vault}"\n'
        f'workspace_location: "{workspace}"\n'
        "available_mcps: []\n"
        'llm_model: ""\n'
        'llm_provider: ""\n'
        "timeout_seconds: 60\n"
        "max_retries: 1\n"
        "base_delay: 0.1\n"
        "backoff_multiplier: 2.0\n"
        "verbosity: quiet\n",
        encoding="utf-8",
    )

    return SimpleNamespace(
        workspace=workspace,
        vault=vault,
        remote=remote,
        config_file=str(config_file),
    )


@pytest.fixture
def e2e_app(e2e_sandbox, monkeypatch):
    monkeypatch.chdir(e2e_sandbox.workspace)
    app = create_application(e2e_sandbox.config_file)
    registry = app.engine._agent_registry.get("Context_Builder")._tool_registry
    fakes = {
        "jira": FakeJiraTool(),
        "obsidian": FakeObsidianTool(e2e_sandbox.vault),
        "opencode": FakeOpenCodeTool(e2e_sandbox.workspace),
    }
    for tool in fakes.values():
        registry.register(tool)
    return app, fakes


def _git(workspace: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_full_workflow_end_to_end(e2e_app, e2e_sandbox):
    app, fakes = e2e_app

    run_record = app.work_command.execute("TEST-1")

    assert run_record.status == "completed"
    assert run_record.verdict == "PASS"
    assert run_record.tests_executed == 1
    assert run_record.tests_passed == 1
    assert run_record.tests_failed == 0
    assert "src/feature.py" in run_record.modified_files
    assert "tests/test_feature.py" in run_record.modified_files

    run_record_path = e2e_sandbox.workspace / "runs" / run_record.run_id / "run-record.json"
    assert run_record_path.exists()

    state = json.loads((e2e_sandbox.workspace / ".autopilot_state.json").read_text(encoding="utf-8"))
    assert any(e.get("type") == "test_result" for e in state["evidence"])
    assert state["metrics"]["published"] is True
    assert state["metadata"]["documentation_status"] == "generated"
    assert state["metadata"]["documentation_draft"].startswith("# Work Summary: TEST-1")

    assert "feature/test-1" in _git(e2e_sandbox.workspace, "branch", "--list")
    commit_msg = _git(e2e_sandbox.workspace, "log", "-1", "--pretty=%s", "feature/test-1")
    assert commit_msg.startswith("feat(TEST-1): ")

    remote_refs = _git(e2e_sandbox.workspace, "ls-remote", "--heads", str(e2e_sandbox.remote))
    assert "refs/heads/feature/test-1" in remote_refs
    assert "refs/heads/develop" in remote_refs

    commit_files = _git(e2e_sandbox.workspace, "show", "--name-only", "--pretty=format:", "feature/test-1")
    assert "src/feature.py" in commit_files
    assert "tests/test_feature.py" in commit_files

    jira_calls = [c for c in fakes["jira"].calls if c.get("action") == "get_ticket"]
    assert len(jira_calls) == 1
    assert jira_calls[0]["ticket_id"] == "TEST-1"
    assert fakes["obsidian"].calls
    assert len(fakes["opencode"].calls) == 3


def test_workflow_applies_vault_rules(e2e_app, e2e_sandbox):
    app, fakes = e2e_app
    rules = (
        "- branch_from: develop\n"
        "- branch_pattern: feature/custom-{ticket_id}-{description}\n"
        "- commit_pattern: feat({ticket_id}): [custom] {description}\n"
        "- jira_transition: In Progress -> Code Review\n"
        "- push_remote: origin\n"
    )
    (e2e_sandbox.vault / RULES_FILENAME).write_text(rules, encoding="utf-8")

    run_record = app.work_command.execute("TEST-1")

    assert run_record.status == "completed"
    assert run_record.verdict == "PASS"

    branch = "feature/custom-test-1-implement-feature-x"
    assert branch in _git(e2e_sandbox.workspace, "branch", "--list")
    commit_msg = _git(e2e_sandbox.workspace, "log", "-1", "--pretty=%s", branch)
    assert commit_msg == "feat(TEST-1): [custom] Implement feature X"

    state = json.loads((e2e_sandbox.workspace / ".autopilot_state.json").read_text(encoding="utf-8"))
    assert state["metrics"]["rules_applied"] == "vault"
    jira_update = state["metrics"]["jira_update"]
    assert jira_update["skipped"] is True
    assert jira_update["transition"] == "In Progress -> Code Review"


def test_cli_work_end_to_end(e2e_app, e2e_sandbox):
    app, fakes = e2e_app

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app):
        runner = CliRunner()
        result = runner.invoke(cli, ["work", "TEST-1", "--skip-validation"])

    assert result.exit_code == 0
    assert "WORKFLOW REPORT" in result.output
    assert "PASS" in result.output

    ledger_path = e2e_sandbox.workspace / "ledger.json"
    assert ledger_path.exists()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert any(
        e.get("ticket_id") == "TEST-1" and e.get("status") == "completed" for e in ledger
    )

    assert "autopilot-results" in _git(e2e_sandbox.workspace, "branch", "--list")
    ledger_at_branch = _git(e2e_sandbox.workspace, "show", "autopilot-results:ledger.json")
    assert "TEST-1" in ledger_at_branch