"""Approval gate interface for human-in-the-loop checkpoints."""

from typing import Any, Protocol


class ApprovalGate(Protocol):
    """Protocol for human-in-the-loop approval checkpoints.

    Implementations decide whether a given gate requires human approval
    (based on configuration), how to present the details, and how to
    collect the decision. Returning False must raise or signal rejection
    so the workflow can stop.
    """

    def require(self, gate_name: str, details: dict[str, Any]) -> bool:
        """Request approval for a gate.

        Args:
            gate_name: Identifier of the gate (e.g. "plan").
            details: Contextual information to present (e.g. the plan).

        Returns:
            True if approved or not required, False if rejected.
        """
        ...


class ApprovalRejected(Exception):
    """Raised by approval gate implementations when a human rejects.

    Kept in the application layer so gate implementations can signal
    rejection without coupling to infrastructure exceptions.
    """

    pass