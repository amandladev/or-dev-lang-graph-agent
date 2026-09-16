"""Workspace entity used to isolate a workflow execution."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Workspace:
    """A ticket-owned Git worktree and its execution metadata."""

    workspace_id: str = ""
    ticket_id: str = ""
    repository_path: str = ""
    path: str = ""
    branch: str = ""
    base_ref: str = ""
    base_commit: str = ""
    status: str = "active"
    agent_id: str = ""
    run_id: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible representation."""
        return {
            "workspace_id": self.workspace_id,
            "ticket_id": self.ticket_id,
            "repository_path": self.repository_path,
            "path": self.path,
            "branch": self.branch,
            "base_ref": self.base_ref,
            "base_commit": self.base_commit,
            "status": self.status,
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        """Create a workspace from persisted metadata."""
        return cls(
            workspace_id=data.get("workspace_id", ""),
            ticket_id=data.get("ticket_id", ""),
            repository_path=data.get("repository_path", ""),
            path=data.get("path", ""),
            branch=data.get("branch", ""),
            base_ref=data.get("base_ref", ""),
            base_commit=data.get("base_commit", ""),
            status=data.get("status", "active"),
            agent_id=data.get("agent_id", ""),
            run_id=data.get("run_id", ""),
            created_at=data.get("created_at", ""),
        )
