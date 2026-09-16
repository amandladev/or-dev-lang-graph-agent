"""Custom domain exceptions for error classification."""


class TestFailureError(Exception):
    """Raised when a test suite execution fails."""

    pass


class ToolTimeoutError(Exception):
    """Raised when a tool execution exceeds its timeout."""

    pass


class AuthenticationError(Exception):
    """Raised when authentication with an external service fails."""

    pass


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


class SchemaViolationError(Exception):
    """Raised when data does not conform to its expected schema."""

    pass


class PublishError(Exception):
    """Raised when the Publisher cannot complete its git workflow.

    Indicates a failed git operation (checkout, branch, commit, or push)
    so the workflow fails loudly instead of reporting a false success.
    """

    pass


class CodeExecutionVerificationError(Exception):
    """Raised when none of the plan's expected files exist in the workspace.

    OpenCode is an external process; nothing prevents it from resolving its
    own working directory to a different project than the one passed via
    subprocess cwd (observed: it can attach to another locally-known
    project/session and write there instead). When that happens the
    workspace worktree is left with no real changes, and downstream agents
    would otherwise report a false PASS on an effectively empty commit.
    """

    pass


class ApprovalRejectedError(Exception):
    """Raised when a human rejects an approval gate (e.g. the plan).

    Non-retryable: the workflow should stop and be marked cancelled rather
    than retried or resumed.
    """

    pass


class NeedsClarificationError(Exception):
    """Raised when an agent cannot proceed without human input.

    Distinct from a generic non-retryable failure: this is not a bug or a
    broken tool, it's the agent surfacing a genuine ambiguity in the task
    (e.g. the ticket doesn't say which of two valid approaches to take).
    The workflow pauses with verdict BLOCKED instead of FAIL, and the
    question is persisted so `autopilot resume --answer "..."` can inject
    the human's answer and resume at the same node that asked.
    """

    def __init__(self, question: str) -> None:
        super().__init__(question)
        self.question = question


class WorkspaceError(Exception):
    """Base error for workspace lifecycle failures."""


class WorkspaceConflictError(WorkspaceError):
    """Raised when a path or branch belongs to another workspace."""


class WorkspaceNotFoundError(WorkspaceError):
    """Raised when persisted workspace metadata cannot be found."""


class WorkspaceDirtyError(WorkspaceError):
    """Raised when cleanup would discard uncommitted changes."""


class WrongWorkspaceError(WorkspaceError):
    """Raised when an operation targets the wrong path or branch."""


class GitOperationError(WorkspaceError):
    """Raised when Git cannot complete a protected workspace operation."""
