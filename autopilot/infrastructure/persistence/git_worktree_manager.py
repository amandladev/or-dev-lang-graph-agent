"""Git worktree lifecycle management for ticket-isolated executions."""

import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from autopilot.domain.entities.workspace import Workspace
from autopilot.domain.value_objects.exceptions import (
    GitOperationError,
    WorkspaceConflictError,
    WorkspaceDirtyError,
    WorkspaceNotFoundError,
    WrongWorkspaceError,
)
from autopilot.infrastructure.persistence.atomic_write import atomic_write_json
from autopilot.infrastructure.persistence.file_lock import LedgerLock, lock_path_for


class GitWorktreeManager:
    """Create, recover and safely remove one worktree per ticket."""

    def __init__(
        self,
        repository: str | Path,
        worktree_root: str | Path,
        rules_provider: Callable[[], dict[str, Any]] | None = None,
        logger: Any | None = None,
    ) -> None:
        self._repository = Path(repository).expanduser().resolve()
        self._worktree_root = Path(worktree_root).expanduser().resolve()
        if self._worktree_root == self._repository or self._repository in self._worktree_root.parents:
            raise ValueError("worktree_root must be outside the source repository")
        self._metadata_root = self._worktree_root / ".autopilot-workspaces"
        self._rules_provider = rules_provider
        self._logger = logger

    @property
    def repository(self) -> Path:
        """Return the canonical source repository path."""
        return self._repository

    @property
    def worktree_root(self) -> Path:
        """Return the root directory for ticket worktrees."""
        return self._worktree_root

    def run_lock_path(self, ticket_id: str) -> Path:
        """Return the deterministic execution lock path for a ticket."""
        return lock_path_for(self._metadata_root / f"{self._ticket_slug(ticket_id)}.run")

    def execution_lock(self, ticket_id: str) -> LedgerLock:
        """Return a non-blocking lock for one ticket's lifecycle."""
        return LedgerLock(self.run_lock_path(ticket_id), blocking=False)

    def create_workspace(
        self,
        ticket: dict[str, Any],
        run_id: str = "",
        agent_id: str = "",
    ) -> Workspace:
        """Create or recover a worktree for a ticket."""
        ticket_id = str(ticket.get("id", "")).strip()
        if not ticket_id:
            raise ValueError("ticket.id is required to create a workspace")
        self._repository = self._resolve_repository(self._repository)

        ticket_slug = self._ticket_slug(ticket_id)
        path = self._worktree_root / ticket_slug
        metadata_path = self._metadata_root / f"{ticket_slug}.json"
        existing = self._load_metadata(metadata_path)
        if existing:
            branch = existing.branch
            rules = {"branch_from": existing.base_ref}
        else:
            rules = self._rules_provider() if self._rules_provider else self._default_rules()
            title = str(ticket.get("title", "implementation"))
            branch = self._branch_name(ticket_id, title, rules)

        self._worktree_root.mkdir(parents=True, exist_ok=True)
        with LedgerLock(lock_path_for(self._worktree_root / ".worktree")):
            existing = self._load_metadata(metadata_path)
            entries = self._worktree_entries()
            registered = self._entry_for_path(entries, path)
            branch_entry = self._entry_for_branch(entries, branch)

            if existing:
                self._validate_metadata(existing, ticket_id, branch, path)
                if branch_entry and Path(branch_entry["path"]).resolve() != path.resolve():
                    raise WorkspaceConflictError(
                        f"Branch '{branch}' is already attached to {branch_entry['path']}"
                    )
                if registered and registered["branch"] not in ("", branch):
                    raise WorkspaceConflictError(f"Path '{path}' belongs to another branch")
                if not registered:
                    self._attach_existing_branch(path, branch)
                existing.status = "active"
                existing.run_id = run_id or existing.run_id
                existing.agent_id = agent_id or existing.agent_id
                self._save_metadata(metadata_path, existing)
                return existing

            if path.exists():
                if not registered or registered["branch"] != branch:
                    raise WorkspaceConflictError(f"Workspace path already exists: {path}")
                if branch_entry and Path(branch_entry["path"]).resolve() != path.resolve():
                    raise WorkspaceConflictError(
                        f"Branch '{branch}' is already attached to {branch_entry['path']}"
                    )

            if branch_entry and Path(branch_entry["path"]).resolve() != path.resolve():
                raise WorkspaceConflictError(
                    f"Branch '{branch}' is already attached to {branch_entry['path']}"
                )

            if self._branch_exists(branch) and not registered:
                raise WorkspaceConflictError(
                    f"Branch '{branch}' already exists without recoverable workspace metadata"
                )

            if registered:
                base_ref = rules.get("branch_from", "develop")
                base_commit = self._resolve_commit(base_ref)
            else:
                base_ref = str(rules.get("branch_from", "develop"))
                base_commit = self._resolve_commit(base_ref)
                self._run_git(
                    "worktree",
                    "add",
                    "--quiet",
                    "-b",
                    branch,
                    str(path),
                    base_commit,
                )

            workspace = Workspace(
                workspace_id=ticket_slug,
                ticket_id=ticket_id,
                repository_path=str(self._repository),
                path=str(path),
                branch=branch,
                base_ref=base_ref,
                base_commit=base_commit,
                status="active",
                agent_id=agent_id,
                run_id=run_id,
            )
            self._save_metadata(metadata_path, workspace)
            self._emit(ticket_id, workspace, "git.worktree.create", "success")
            return workspace

    def get_workspace(self, ticket_id: str) -> Workspace:
        """Load persisted workspace metadata for a ticket."""
        metadata_path = self._metadata_root / f"{self._ticket_slug(ticket_id)}.json"
        workspace = self._load_metadata(metadata_path)
        if workspace is None:
            raise WorkspaceNotFoundError(f"Workspace not found for ticket '{ticket_id}'")
        return workspace

    def get_workspace_status(self, workspace: Workspace | str) -> dict[str, Any]:
        """Return the current branch, validity and dirty state."""
        current = self._resolve_workspace(workspace)
        path = Path(current.path)
        changes: list[str] = []
        actual_branch = ""
        valid = False
        error = ""
        if path.is_dir():
            try:
                actual_branch = self._run_git_at(path, "branch", "--show-current").stdout.strip()
                status = self._run_git_at(path, "status", "--porcelain", "--untracked-files=all")
                changes = [line for line in status.stdout.splitlines() if line]
                actual_root = self._run_git_at(path, "rev-parse", "--show-toplevel").stdout.strip()
                valid = Path(actual_root).resolve() == path.resolve() and actual_branch == current.branch
            except GitOperationError as exc:
                error = str(exc)
        else:
            error = f"Workspace path does not exist: {path}"

        state = "active" if valid and not changes else "dirty" if valid else "invalid"
        return {
            "workspace": current.to_dict(),
            "path": str(path),
            "branch": actual_branch,
            "expected_branch": current.branch,
            "changes": changes,
            "clean": not changes,
            "valid": valid,
            "status": state,
            "error": error,
        }

    def assert_workspace(self, workspace: Workspace, cwd: str | Path | None = None) -> None:
        """Verify that a path is the expected worktree and branch."""
        candidate = Path(cwd or workspace.path).expanduser().resolve()
        expected = Path(workspace.path).expanduser().resolve()
        if candidate != expected:
            raise WrongWorkspaceError(f"Expected workspace '{expected}', got '{candidate}'")
        status = self.get_workspace_status(workspace)
        if not status["valid"]:
            raise WrongWorkspaceError(status["error"] or "Workspace branch/path validation failed")

    def remove_workspace(
        self,
        workspace: Workspace | str,
        delete_branch: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """Remove a worktree without discarding changes by default."""
        current = self._resolve_workspace(workspace)
        status = self.get_workspace_status(current)
        if status["changes"] and not force:
            raise WorkspaceDirtyError(
                f"Workspace '{current.path}' contains uncommitted changes"
            )

        with LedgerLock(lock_path_for(self._worktree_root / ".worktree")):
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(current.path)
            self._run_git(*args)
            if delete_branch:
                self._run_git("branch", "-d", current.branch)
            self._delete_metadata(current.ticket_id)
            self._emit(current.ticket_id, current, "git.worktree.remove", "success")
        return {"removed": True, "branch_deleted": delete_branch, "workspace": current.to_dict()}

    def cleanup_workspace(self, workspace: Workspace | str, merged: bool = False) -> dict[str, Any]:
        """Remove a clean workspace, preserving dirty worktrees."""
        current = self._resolve_workspace(workspace)
        status = self.get_workspace_status(current)
        if status["changes"]:
            current.status = "dirty"
            self._save_metadata(self._metadata_path(current.ticket_id), current)
            return {
                "removed": False,
                "preserved": True,
                "status": "dirty",
                "changes": status["changes"],
                "workspace": current.to_dict(),
            }

        with LedgerLock(lock_path_for(self._worktree_root / ".worktree")):
            self._run_git("worktree", "remove", current.path)
            if merged:
                self._run_git("branch", "-D", current.branch)
            self._delete_metadata(current.ticket_id)
            self._emit(current.ticket_id, current, "git.worktree.cleanup", "success")
        return {"removed": True, "preserved": False, "status": "cleaned", "workspace": current.to_dict()}

    def _resolve_workspace(self, workspace: Workspace | str) -> Workspace:
        return workspace if isinstance(workspace, Workspace) else self.get_workspace(workspace)

    def _resolve_repository(self, repository: str | Path) -> Path:
        path = Path(repository).expanduser().resolve()
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitOperationError(result.stderr.strip() or f"Not a Git repository: {path}")
        return Path(result.stdout.strip()).resolve()

    def _run_git(self, *args: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", "-C", str(self._repository), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitOperationError(
                f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    def _run_git_at(self, path: Path, *args: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitOperationError(
                f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    def _resolve_commit(self, ref: str) -> str:
        return self._run_git("rev-parse", f"{ref}^{{commit}}").stdout.strip()

    def _branch_exists(self, branch: str) -> bool:
        return self._run_git_optional(
            "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
        ).returncode == 0

    def _run_git_optional(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self._repository), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def _worktree_entries(self) -> list[dict[str, str]]:
        result = self._run_git("worktree", "list", "--porcelain")
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.splitlines() + [""]:
            if line.startswith("worktree "):
                if current:
                    entries.append(current)
                current = {"path": line[9:]}
            elif line.startswith("branch "):
                current["branch"] = line[7:].removeprefix("refs/heads/")
            elif not line and current:
                entries.append(current)
                current = {}
        return entries

    def _entry_for_path(self, entries: list[dict[str, str]], path: Path) -> dict[str, str] | None:
        expected = path.resolve()
        for entry in entries:
            if Path(entry["path"]).resolve() == expected:
                return entry
        return None

    def _entry_for_branch(self, entries: list[dict[str, str]], branch: str) -> dict[str, str] | None:
        return next((entry for entry in entries if entry.get("branch") == branch), None)

    def _attach_existing_branch(self, path: Path, branch: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._run_git("worktree", "add", "--quiet", str(path), branch)

    def _load_metadata(self, path: Path) -> Workspace | None:
        if not path.exists():
            return None
        try:
            import json

            return Workspace.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise WorkspaceConflictError(f"Invalid workspace metadata: {path}: {exc}") from exc

    def _save_metadata(self, path: Path, workspace: Workspace) -> None:
        atomic_write_json(path, workspace.to_dict())

    def _delete_metadata(self, ticket_id: str) -> None:
        path = self._metadata_path(ticket_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _metadata_path(self, ticket_id: str) -> Path:
        return self._metadata_root / f"{self._ticket_slug(ticket_id)}.json"

    def _validate_metadata(self, workspace: Workspace, ticket_id: str, branch: str, path: Path) -> None:
        if workspace.ticket_id != ticket_id or workspace.branch != branch or Path(workspace.path).resolve() != path.resolve():
            raise WorkspaceConflictError("Persisted workspace metadata does not match ticket, branch or path")
        if Path(workspace.repository_path).resolve() != self._repository:
            raise WorkspaceConflictError("Persisted workspace belongs to another repository")

    @staticmethod
    def _ticket_slug(ticket_id: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", ticket_id.lower()).strip("-")
        return slug or "ticket"

    @staticmethod
    def _title_slug(title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return (slug or "implementation")[:30].rstrip("-") or "implementation"

    def _branch_name(self, ticket_id: str, title: str, rules: dict[str, Any]) -> str:
        try:
            branch = str(rules.get("branch_pattern", "feature/{ticket_id}")).format(
                ticket_id=ticket_id.lower(), description=self._title_slug(title)
            )
        except (KeyError, ValueError) as exc:
            raise WorkspaceConflictError(f"Invalid branch pattern: {exc}") from exc
        result = self._run_git_optional("check-ref-format", "--branch", branch)
        if result.returncode != 0 or branch.startswith("-"):
            raise WorkspaceConflictError(f"Invalid branch name generated for ticket '{ticket_id}': {branch}")
        return branch

    @staticmethod
    def _default_rules() -> dict[str, str]:
        return {"branch_from": "develop", "branch_pattern": "feature/{ticket_id}"}

    def _emit(self, ticket_id: str, workspace: Workspace, operation: str, status: str) -> None:
        if self._logger is not None and hasattr(self._logger, "log_workspace_operation"):
            self._logger.log_workspace_operation(
                ticket_id=ticket_id,
                workspace_id=workspace.workspace_id,
                workspace_path=workspace.path,
                branch=workspace.branch,
                operation=operation,
                status=status,
            )
