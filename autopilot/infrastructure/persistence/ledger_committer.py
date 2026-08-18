"""Ledger committer for git persistence.

Commits the ledger to a dedicated git branch (autopilot-results) for
version control and audit trail. Uses a single-writer pattern to prevent
concurrent commit conflicts.
"""

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class LedgerCommitter:
    """Commits ledger changes to a dedicated git branch.

    The ledger is committed to the 'autopilot-results' branch, keeping
    the main branch clean. This provides:
    - Version history of all executions
    - Ability to diff between runs
    - Offline access to historical data
    - Single-writer pattern for concurrency safety
    """

    BRANCH_NAME = "autopilot-results"

    def __init__(self, workspace: str | Path) -> None:
        """Initialize the ledger committer.

        Args:
            workspace: Root workspace directory containing the git repo.
        """
        self._workspace = Path(workspace)

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command.

        Args:
            *args: Git command arguments.
            check: Whether to raise on non-zero exit.

        Returns:
            CompletedProcess result.
        """
        return subprocess.run(
            ["git", *args],
            cwd=self._workspace,
            capture_output=True,
            text=True,
            check=check,
        )

    def _branch_exists(self, branch: str) -> bool:
        """Check if a git branch exists."""
        result = self._run_git("branch", "--list", branch, check=False)
        return bool(result.stdout.strip())

    def _ensure_branch(self) -> bool:
        """Ensure the autopilot-results branch exists, creating it if needed.

        Creates the branch with a commit-tree ref update (no checkout), so
        the caller's working tree and current branch are never touched.

        Returns:
            True if the branch exists afterwards, False on failure.
        """
        if self._branch_exists(self.BRANCH_NAME):
            return True
        empty_tree = self._run_git("hash-object", "-t", "tree", "/dev/null").stdout.strip()
        result = self._run_git(
            "commit-tree", empty_tree, "-m", "Initial autopilot-results branch",
            check=False,
        )
        if result.returncode != 0:
            log.warning("Could not create branch %s: %s", self.BRANCH_NAME, result.stderr)
            return False
        self._run_git(
            "update-ref", f"refs/heads/{self.BRANCH_NAME}", result.stdout.strip(),
            check=False,
        )
        return True

    def _is_git_repo(self) -> bool:
        """Check if the workspace is a git repository."""
        result = self._run_git("rev-parse", "--git-dir", check=False)
        return result.returncode == 0

    def commitledger(
        self,
        ledger_path: str | Path,
        message: str,
        files: list[str] | None = None,
    ) -> bool:
        """Commit ledger and optional files to the autopilot-results branch.

        Uses a single-writer pattern: stages the ledger, creates the commit
        with commit-tree, and advances the branch ref with update-ref. Never
        checks out the results branch, so the working tree and the caller's
        current branch are left untouched (the ledger file stays on disk).

        Args:
            ledger_path: Path to the ledger.json file.
            message: Commit message.
            files: Optional list of additional file paths to commit.

        Returns:
            True if commit was successful, False otherwise.
        """
        # Check if workspace is a git repo
        if not self._is_git_repo():
            log.info("Not a git repository, skipping ledger commit")
            return False

        try:
            # Ensure target branch exists
            if not self._ensure_branch():
                return False

            # Stage the ledger
            if Path(ledger_path).exists():
                self._run_git("add", str(ledger_path))

            # Stage additional files if provided
            if files:
                for f in files:
                    self._run_git("add", f)

            # No changes to commit if the ledger already matches the branch
            if Path(ledger_path).exists() and not files:
                rel = os.path.relpath(Path(ledger_path), self._workspace)
                branch_ledger = self._run_git(
                    "show", f"{self.BRANCH_NAME}:{rel}", check=False
                )
                if (
                    branch_ledger.returncode == 0
                    and branch_ledger.stdout == Path(ledger_path).read_text(encoding="utf-8")
                ):
                    log.info("No changes to commit")
                    return True

            # Create the commit and advance the branch ref
            tree = self._run_git("write-tree").stdout.strip()
            parent = self._run_git("rev-parse", self.BRANCH_NAME).stdout.strip()
            result = self._run_git(
                "commit-tree", tree, "-p", parent, "-m", message, check=False
            )
            if result.returncode != 0:
                log.error("Failed to create commit: %s", result.stderr)
                return False
            self._run_git(
                "update-ref", f"refs/heads/{self.BRANCH_NAME}", result.stdout.strip(),
                check=False,
            )

            # Unstage what we staged, keeping the working tree intact
            self._run_git("reset", "-q", check=False)

            log.info("Committed to %s: %s", self.BRANCH_NAME, message)
            return True

        except subprocess.CalledProcessError as e:
            log.error("Git error: %s", e.stderr)
            return False

    def get_last_commits(self, count: int = 10) -> list[dict]:
        """Get recent commits from the autopilot-results branch.

        Args:
            count: Number of commits to retrieve.

        Returns:
            List of commit dicts with hash, message, date.
        """
        result = self._run_git(
            "log", self.BRANCH_NAME,
            f"-{count}",
            "--pretty=format:%H|%s|%ai",
            check=False,
        )
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "date": parts[2],
                })
        return commits

    def get_ledger_at_commit(self, commit_hash: str, ledger_path: str) -> dict | None:
        """Get the ledger content at a specific commit.

        Args:
            commit_hash: The commit hash to retrieve.
            ledger_path: Path to the ledger file relative to workspace.

        Returns:
            Parsed ledger JSON at that commit, or None if not found.
        """
        result = self._run_git(
            "show", f"{commit_hash}:{ledger_path}",
            check=False,
        )
        if result.returncode != 0:
            return None

        try:
            import json
            return json.loads(result.stdout)
        except Exception:
            return None
