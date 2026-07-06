"""Ledger committer for git persistence.

Commits the ledger to a dedicated git branch (autopilot-results) for
version control and audit trail. Uses a single-writer pattern to prevent
concurrent commit conflicts.
"""

import subprocess
import logging
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

    def _ensure_branch(self) -> None:
        """Ensure the autopilot-results branch exists, creating it if needed."""
        if not self._branch_exists(self.BRANCH_NAME):
            # Create orphan branch from current state
            result = self._run_git("checkout", "-b", self.BRANCH_NAME, check=False)
            if result.returncode != 0:
                # Branch might already exist from another process
                result = self._run_git("checkout", self.BRANCH_NAME, check=False)
                if result.returncode != 0:
                    log.warning("Could not create/checkout branch %s: %s",
                                self.BRANCH_NAME, result.stderr)
                    return
            # Commit current state as initial
            self._run_git("add", "-A", check=False)
            self._run_git("commit", "--allow-empty", "-m",
                          "Initial autopilot-results branch", check=False)
            # Return to previous branch
            self._run_git("checkout", "-", check=False)

    def commitledger(
        self,
        ledger_path: str | Path,
        message: str,
        files: list[str] | None = None,
    ) -> bool:
        """Commit ledger and optional files to the autopilot-results branch.

        Uses a single-writer pattern: checks out the branch, stages files,
        commits, and returns to the previous branch.

        Args:
            ledger_path: Path to the ledger.json file.
            message: Commit message.
            files: Optional list of additional file paths to commit.

        Returns:
            True if commit was successful, False otherwise.
        """
        try:
            # Save current branch
            current = self._run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

            # Ensure target branch exists
            self._ensure_branch()

            # Checkout the results branch
            result = self._run_git("checkout", self.BRANCH_NAME, check=False)
            if result.returncode != 0:
                log.error("Failed to checkout %s: %s", self.BRANCH_NAME, result.stderr)
                return False

            # Stage the ledger
            self._run_git("add", str(ledger_path))

            # Stage additional files if provided
            if files:
                for f in files:
                    self._run_git("add", f)

            # Check if there are changes to commit
            status = self._run_git("status", "--porcelain")
            if not status.stdout.strip():
                log.info("No changes to commit")
                self._run_git("checkout", current, check=False)
                return True

            # Commit
            self._run_git("commit", "-m", message)

            # Return to original branch
            self._run_git("checkout", current)

            log.info("Committed to %s: %s", self.BRANCH_NAME, message)
            return True

        except subprocess.CalledProcessError as e:
            log.error("Git error: %s", e.stderr)
            # Try to return to original branch
            try:
                self._run_git("checkout", "-", check=False)
            except Exception:
                pass
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
