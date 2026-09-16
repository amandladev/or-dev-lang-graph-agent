"""Tests for CodeExecutorAgent's git-based modified-files detection.

Regression coverage for: `_extract_modified_files` used to be the sole
source of `modified_files`, parsing OpenCode's free-text stdout for
prefixes like "Modified:" — brittle and likely to under/over-report.
`_git_modified_files` uses `git status --porcelain` as ground truth when
available, with the text heuristic only as a fallback for non-git dirs.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from autopilot.domain.value_objects.exceptions import CodeExecutionVerificationError
from autopilot.infrastructure.agents.code_executor import CodeExecutorAgent


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


@pytest.fixture
def git_repo(tmp_path, monkeypatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "existing.txt").write_text("original\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial commit")

    monkeypatch.chdir(repo)
    return repo


def test_git_modified_files_returns_none_outside_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent = CodeExecutorAgent(tool_registry=MagicMock())

    assert agent._git_modified_files() is None


def test_git_modified_files_detects_untracked_file(git_repo):
    (git_repo / "new_file.py").write_text("print('hi')\n")
    agent = CodeExecutorAgent(tool_registry=MagicMock())

    result = agent._git_modified_files()

    assert result == ["new_file.py"]


def test_git_modified_files_detects_modified_tracked_file(git_repo):
    (git_repo / "existing.txt").write_text("changed\n")
    agent = CodeExecutorAgent(tool_registry=MagicMock())

    result = agent._git_modified_files()

    assert result == ["existing.txt"]


def test_git_modified_files_no_changes_returns_empty_list(git_repo):
    agent = CodeExecutorAgent(tool_registry=MagicMock())

    assert agent._git_modified_files() == []


def test_execute_prefers_git_detection_over_text_heuristic(git_repo):
    """Even if OpenCode's stdout doesn't match any recognized text prefix
    (so the heuristic would find nothing), the real git-detected file
    should still be reported."""
    (git_repo / "real_change.py").write_text("x = 1\n")

    plan = {
        "ticket_id": "T-1",
        "steps": [{"step": 1, "description": "Do the thing"}],
    }
    opencode = MagicMock()
    opencode.execute.return_value = MagicMock(
        success=True, data={"result": "some unstructured free-text output"}
    )
    registry = MagicMock()
    registry.get.return_value = opencode
    agent = CodeExecutorAgent(tool_registry=registry)

    output = agent.execute({"plan": plan, "context": {}})

    assert output["modified_files"] == ["real_change.py"]


class TestExpectedFilesVerification:
    """OpenCode is an external process and can resolve its own working
    directory to a different, previously-known project instead of the
    worktree passed via subprocess cwd — silently writing changes there
    (observed against a real opencode install with a stale local session).
    When that happens the workspace ends up with no real changes, and
    without this guard every downstream agent reports a false PASS on an
    effectively empty commit."""

    def _run(self, git_repo: Path, expected_files: list[str]) -> None:
        plan = {
            "ticket_id": "T-1",
            "steps": [{"step": 1, "description": "Do the thing"}],
            "expected_files": expected_files,
        }
        opencode = MagicMock()
        opencode.execute.return_value = MagicMock(
            success=True, data={"result": "done"}
        )
        registry = MagicMock()
        registry.get.return_value = opencode
        agent = CodeExecutorAgent(tool_registry=registry)
        agent.execute(
            {"plan": plan, "context": {}, "workspace": {"path": str(git_repo)}}
        )

    def test_raises_when_no_expected_file_exists_in_workspace(self, git_repo):
        with pytest.raises(CodeExecutionVerificationError):
            self._run(git_repo, ["src/todo.py", "tests/test_todo.py"])

    def test_passes_when_an_expected_file_exists_on_disk(self, git_repo):
        (git_repo / "src").mkdir()
        (git_repo / "src" / "todo.py").write_text("x = 1\n")

        self._run(git_repo, ["src/todo.py", "tests/test_todo.py"])

    def test_passes_when_an_expected_file_is_in_modified_files(self, git_repo):
        # existing.txt is tracked in the git_repo fixture; modifying it is
        # picked up by `_git_modified_files` even though it isn't newly
        # created, which is enough to prove real work happened here.
        (git_repo / "existing.txt").write_text("changed\n")

        self._run(git_repo, ["existing.txt"])

    def test_skips_verification_without_expected_files(self, git_repo):
        self._run(git_repo, [])

    def test_skips_verification_without_a_workspace_path(self):
        plan = {
            "ticket_id": "T-1",
            "steps": [{"step": 1, "description": "Do the thing"}],
            "expected_files": ["src/todo.py"],
        }
        opencode = MagicMock()
        opencode.execute.return_value = MagicMock(success=True, data={"result": "done"})
        registry = MagicMock()
        registry.get.return_value = opencode
        agent = CodeExecutorAgent(tool_registry=registry)

        # No "workspace" key at all — legacy/no-worktree mode. Nothing to
        # verify against, so this must not raise.
        agent.execute({"plan": plan, "context": {}})
