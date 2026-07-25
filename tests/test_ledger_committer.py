"""Tests for LedgerCommitter, focused on the branch-restore bug fix.

Regression coverage for: `commitledger`'s exception handler used to run
`git checkout "-"` (toggle to the previous branch) instead of the branch
that was actually checked out before the call started. That can strand
the repo on `autopilot-results` if the caller had switched branches earlier
in the session (so "previous" != "current").
"""

import subprocess
from pathlib import Path

import pytest

from autopilot.infrastructure.persistence.ledger_committer import LedgerCommitter


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


def _current_branch(cwd: Path) -> str:
    result = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path) -> Path:
    """A real git repo with two branches, ending checked out on 'trunk'
    after having previously visited 'sidetrack' — so git's "previous
    branch" toggle ("checkout -") would resolve to 'sidetrack', not
    'trunk'. This is the exact scenario that exposes the bug."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "trunk")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial commit")

    # Visit a different branch, then come back to trunk. This makes
    # "previous branch" (used by `checkout -`) resolve to 'sidetrack'.
    _git(repo, "checkout", "-b", "sidetrack")
    _git(repo, "checkout", "trunk")

    ledger_path = repo / "ledger.json"
    ledger_path.write_text("[]\n")

    return repo


def test_commitledger_not_a_git_repo_returns_false(tmp_path):
    committer = LedgerCommitter(workspace=tmp_path)
    result = committer.commitledger(ledger_path=str(tmp_path / "ledger.json"), message="test")
    assert result is False


def test_commitledger_success_restores_original_branch(git_repo):
    committer = LedgerCommitter(workspace=git_repo)

    result = committer.commitledger(
        ledger_path=str(git_repo / "ledger.json"), message="run abc123"
    )

    assert result is True
    assert _current_branch(git_repo) == "trunk"


def test_commitledger_error_during_commit_restores_current_not_previous(git_repo, monkeypatch):
    """Force a failure inside the try block (after `current` has been
    captured and after checking out BRANCH_NAME) and verify the repo is
    restored to `current` ('trunk'), not to git's toggle target
    ('sidetrack')."""
    committer = LedgerCommitter(workspace=git_repo)
    original_run_git = committer._run_git

    def failing_run_git(*args, check=True):
        if args and args[0] == "commit":
            raise subprocess.CalledProcessError(returncode=1, cmd=["git", "commit"], stderr="boom")
        return original_run_git(*args, check=check)

    monkeypatch.setattr(committer, "_run_git", failing_run_git)

    result = committer.commitledger(
        ledger_path=str(git_repo / "ledger.json"), message="run abc123"
    )

    assert result is False
    assert _current_branch(git_repo) == "trunk"


def test_commitledger_no_changes_restores_original_branch(git_repo):
    committer = LedgerCommitter(workspace=git_repo)

    # First commit succeeds and leaves the ledger tracked on the results
    # branch with no diff; a second call should hit the "no changes"
    # early-return path and still restore to 'trunk'.
    committer.commitledger(ledger_path=str(git_repo / "ledger.json"), message="first")
    result = committer.commitledger(ledger_path=str(git_repo / "ledger.json"), message="second")

    assert result is True
    assert _current_branch(git_repo) == "trunk"
