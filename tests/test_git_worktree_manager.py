"""Tests for ticket-isolated Git workspaces."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autopilot.domain.value_objects.exceptions import (
    GitOperationError,
    PublishError,
    WorkspaceConflictError,
    WorkspaceDirtyError,
    WrongWorkspaceError,
)
from autopilot.infrastructure.agents.publisher import PublisherAgent
from autopilot.infrastructure.persistence.git_worktree_manager import GitWorktreeManager


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "develop")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo, tmp_path / "worktrees"


def test_create_workspace_creates_deterministic_branch_and_path(repository):
    repo, root = repository
    manager = GitWorktreeManager(repo, root)

    workspace = manager.create_workspace({"id": "WPD-619"})

    assert workspace.path == str(root / "wpd-619")
    assert workspace.branch == "feature/wpd-619"
    assert Path(workspace.path).is_dir()
    assert _git(Path(workspace.path), "branch", "--show-current") == workspace.branch
    assert manager.get_workspace("WPD-619").to_dict() == workspace.to_dict()


def test_multiple_workspaces_are_isolated(repository):
    repo, root = repository
    manager = GitWorktreeManager(repo, root)

    first = manager.create_workspace({"id": "WPD-619"})
    second = manager.create_workspace({"id": "WPD-620"})
    Path(first.path, "only-first.txt").write_text("first\n", encoding="utf-8")

    assert not Path(second.path, "only-first.txt").exists()
    assert manager.get_workspace_status(first)["status"] == "dirty"
    assert manager.get_workspace_status(second)["status"] == "active"


def test_multiple_workspaces_can_be_created_concurrently(repository):
    repo, root = repository
    manager = GitWorktreeManager(repo, root)

    with ThreadPoolExecutor(max_workers=3) as executor:
        workspaces = list(
            executor.map(
                lambda ticket: manager.create_workspace({"id": ticket}),
                ["WPD-619", "WPD-620", "WPD-621"],
            )
        )

    assert {workspace.branch for workspace in workspaces} == {
        "feature/wpd-619",
        "feature/wpd-620",
        "feature/wpd-621",
    }


def test_create_workspace_recovers_existing_metadata(repository):
    repo, root = repository
    first_manager = GitWorktreeManager(repo, root)
    first = first_manager.create_workspace({"id": "WPD-619"}, run_id="run-1")

    second = GitWorktreeManager(repo, root).create_workspace(
        {"id": "WPD-619"}, run_id="run-2"
    )

    assert second.path == first.path
    assert second.branch == first.branch
    assert second.run_id == "run-2"


def test_existing_branch_without_metadata_is_rejected(repository):
    repo, root = repository
    _git(repo, "branch", "feature/wpd-619")
    manager = GitWorktreeManager(repo, root)

    with pytest.raises(WorkspaceConflictError):
        manager.create_workspace({"id": "WPD-619"})


def test_wrong_workspace_is_rejected(repository):
    repo, root = repository
    manager = GitWorktreeManager(repo, root)
    workspace = manager.create_workspace({"id": "WPD-619"})

    with pytest.raises(WrongWorkspaceError):
        manager.assert_workspace(workspace, root / "other")


def test_cleanup_preserves_dirty_workspace(repository):
    repo, root = repository
    manager = GitWorktreeManager(repo, root)
    workspace = manager.create_workspace({"id": "WPD-619"})
    Path(workspace.path, "pending.txt").write_text("keep me\n", encoding="utf-8")

    result = manager.cleanup_workspace(workspace)

    assert result["preserved"] is True
    assert Path(workspace.path).is_dir()
    with pytest.raises(WorkspaceDirtyError):
        manager.remove_workspace(workspace)


def test_cleanup_removes_clean_workspace_and_explicitly_deletes_branch(repository):
    repo, root = repository
    manager = GitWorktreeManager(repo, root)
    workspace = manager.create_workspace({"id": "WPD-619"})

    result = manager.cleanup_workspace(workspace, merged=True)

    assert result["removed"] is True
    assert not Path(workspace.path).exists()
    assert "feature/wpd-619" not in _git(repo, "branch", "--list")


def test_non_git_repository_fails_when_creation_is_requested(tmp_path):
    manager = GitWorktreeManager(tmp_path / "not-repo", tmp_path / "worktrees")

    with pytest.raises(GitOperationError):
        manager.create_workspace({"id": "WPD-619"})


def test_publisher_rejects_workspace_with_wrong_branch(repository):
    repo, root = repository
    manager = GitWorktreeManager(repo, root)
    workspace = manager.create_workspace({"id": "WPD-619"})
    invalid = {**workspace.to_dict(), "branch": "feature/wpd-620"}
    publisher = PublisherAgent(MagicMock())

    with patch.object(publisher, "_load_rules", return_value={"jira_transition": ""}):
        with pytest.raises(PublishError):
            publisher.execute({
                "ticket": {"id": "WPD-619", "title": "change"},
                "evidence": [],
                "modified_files": ["README.md"],
                "workspace": invalid,
            })
