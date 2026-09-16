"""Workspace management port."""

from typing import Any, Protocol, runtime_checkable

from autopilot.domain.entities.workspace import Workspace


@runtime_checkable
class WorkspaceManagerInterface(Protocol):
    """Contract for creating and validating ticket workspaces."""

    def create_workspace(
        self,
        ticket: dict[str, Any],
        run_id: str = "",
        agent_id: str = "",
    ) -> Workspace:
        """Create or recover the workspace for a ticket."""
        ...

    def get_workspace(self, ticket_id: str) -> Workspace:
        """Load a persisted workspace by ticket ID."""
        ...

    def get_workspace_status(self, workspace: Workspace | str) -> dict[str, Any]:
        """Return branch, path and dirty-state information."""
        ...

    def execution_lock(self, ticket_id: str) -> Any:
        """Return a context manager that serializes one ticket's workflow."""
        ...

    def remove_workspace(
        self,
        workspace: Workspace | str,
        delete_branch: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """Remove a workspace, refusing dirty worktrees by default."""
        ...

    def cleanup_workspace(
        self,
        workspace: Workspace | str,
        merged: bool = False,
    ) -> dict[str, Any]:
        """Clean up a workspace after a successful lifecycle."""
        ...
