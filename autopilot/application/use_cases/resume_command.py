"""ResumeCommand use case for resuming a paused or failed workflow."""

import uuid

from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.application.orchestrator.graph_builder import WORK_GRAPH_NODES, GraphBuilder
from autopilot.domain.entities.config import Config
from autopilot.domain.interfaces.serializer import SerializerInterface

# Mapping from agent registry names to graph node names.
_AGENT_TO_NODE: dict[str, str] = {
    "Context_Builder": "context_builder",
    "Planner": "planner",
    "Code_Executor": "code_executor",
    "Tester": "tester",
    "Publisher": "publisher",
    "Documentation_Agent": "documentation",
}


class ResumeCommand:
    """Use case that resumes a previously paused or failed workflow.

    Loads the most recent persisted state, identifies the resume point
    from execution logs, builds a resume graph starting at the next node,
    and executes it.
    """

    def __init__(
        self,
        engine: OrchestrationEngine,
        graph_builder: GraphBuilder,
        serializer: SerializerInterface,
        config: Config,
        workspace_manager=None,
    ) -> None:
        """Initialize the ResumeCommand use case.

        Args:
            engine: The orchestration engine for executing graphs.
            graph_builder: Builder for constructing workflow graphs.
            serializer: Serializer for state persistence and loading.
            config: Application configuration.
        """
        self._engine = engine
        self._graph_builder = graph_builder
        self._serializer = serializer
        self._config = config
        self._workspace_manager = workspace_manager

    def execute(self, ticket_id: str = "", answer: str = "") -> str:
        """Resume a ticket while serializing access to its worktree.

        Args:
            ticket_id: The ticket whose workspace should be resumed.
            answer: A human's answer to a pending clarification question.
                Required (raises ValueError otherwise) when the persisted
                state has a pending_question; ignored otherwise.
        """
        if ticket_id and self._workspace_manager is not None:
            with self._workspace_manager.execution_lock(ticket_id):
                return self._execute(ticket_id, answer)
        return self._execute(ticket_id, answer)

    def _execute(self, ticket_id: str = "", answer: str = "") -> str:
        """Resume a previously paused or failed workflow.

        Two resume paths:

        - **Blocked on a clarification question**: the persisted state has
          a pending_question. The human's answer is injected into context
          and the graph resumes at the SAME node that asked (it never
          produced valid output, so the next node can't run yet) — found
          via pending_question["agent_name"], not the log heuristic below.
        - **Otherwise** (paused/failed on a regular error): inspect the
          logs to find the last agent with status "success", and resume
          from the node after it.

        Returns:
            A unique execution ID (UUID) for tracking this resumed workflow run.

        Raises:
            ValueError: If the state is blocked on a clarification question
                but no answer was provided.
        """
        state_filepath = f"{self._config.workspace_location}/.autopilot_state.json"
        if ticket_id and self._workspace_manager is not None:
            workspace = self._workspace_manager.get_workspace(ticket_id)
            state_filepath = f"{workspace.path}/.autopilot_state.json"
        restored_state = self._serializer.load(state_filepath)

        state_dict = self._state_to_dict(restored_state)

        pending_question = state_dict.get("pending_question")
        if pending_question:
            if not answer:
                question = pending_question.get("question", "")
                raise ValueError(
                    "This run is blocked on a clarification question and needs "
                    f"an answer to resume: {question!r}. Pass it with "
                    "`autopilot resume --ticket <id> --answer \"...\"`."
                )
            resume_from = _AGENT_TO_NODE.get(
                pending_question.get("agent_name", ""), WORK_GRAPH_NODES[0]
            )
            state_dict = self._apply_clarification_answer(state_dict, pending_question, answer)
        else:
            resume_from = self._find_resume_node(state_dict.get("logs", []))

        graph = self._graph_builder.build_resume_graph(resume_from)

        self._engine.execute(graph, state_dict)

        execution_id = str(uuid.uuid4())
        return execution_id

    def _apply_clarification_answer(
        self, state_dict: dict, pending_question: dict, answer: str
    ) -> dict:
        """Inject a human's answer into context and clear pending_question.

        The answer lands in context (not the ticket) so PlannerAgent (and
        any future agent wired the same way) picks it up via its existing
        "context" input without a schema change to the ticket itself.

        Args:
            state_dict: The restored graph state.
            pending_question: The pending_question dict from persisted state.
            answer: The human's answer text.

        Returns:
            A new state dict with the answer in context and pending_question
            cleared, ready to pass to engine.execute().
        """
        context = dict(state_dict.get("context", {}))
        context["clarification_question"] = pending_question.get("question", "")
        context["clarification_answer"] = answer
        return {**state_dict, "context": context, "pending_question": None}

    def _find_resume_node(self, logs: list) -> str:
        """Identify the node to resume from based on execution logs.

        Inspects the logs to find the last agent with status "success",
        then returns the next node in the workflow order.

        If no logs exist or no successful steps are found, resumes from
        the beginning (context_builder).

        Args:
            logs: List of log entries (dicts or LogEntry objects).

        Returns:
            The node name to resume execution from.
        """
        if not logs:
            return WORK_GRAPH_NODES[0]  # "context_builder"

        # Find the last log entry with status "success"
        last_successful_agent: str | None = None
        for log_entry in logs:
            status = self._get_log_status(log_entry)
            if status == "success":
                last_successful_agent = self._get_log_agent_name(log_entry)

        if last_successful_agent is None:
            return WORK_GRAPH_NODES[0]  # "context_builder"

        # Map agent name to graph node name
        node_name = _AGENT_TO_NODE.get(last_successful_agent, last_successful_agent)

        # Find the next node in the workflow order
        if node_name in WORK_GRAPH_NODES:
            node_index = WORK_GRAPH_NODES.index(node_name)
            next_index = node_index + 1
            if next_index < len(WORK_GRAPH_NODES):
                return WORK_GRAPH_NODES[next_index]
            else:
                # Last node was already successful; resume from it anyway
                # (edge case: workflow was fully complete)
                return WORK_GRAPH_NODES[-1]

        # If we can't map the agent to a known node, start from beginning
        return WORK_GRAPH_NODES[0]

    def _get_log_status(self, log_entry) -> str:
        """Extract the status string from a log entry.

        Handles both dict representations and LogEntry dataclass instances.

        Args:
            log_entry: A log entry (dict or LogEntry object).

        Returns:
            The status string (e.g., "success", "failed", "skipped").
        """
        if isinstance(log_entry, dict):
            status = log_entry.get("status", "")
            # Handle enum-tagged dicts from serialization
            if isinstance(status, dict) and status.get("__type__") == "enum":
                return status.get("value", "")
            return str(status)
        # LogEntry dataclass or similar object with status attribute
        status = getattr(log_entry, "status", None)
        if status is not None:
            if hasattr(status, "value"):
                return status.value
            return str(status)
        return ""

    def _get_log_agent_name(self, log_entry) -> str:
        """Extract the agent name from a log entry.

        Handles both dict representations and LogEntry dataclass instances.

        Args:
            log_entry: A log entry (dict or LogEntry object).

        Returns:
            The agent name string.
        """
        if isinstance(log_entry, dict):
            return log_entry.get("agent_name", "")
        return getattr(log_entry, "agent_name", "")

    def _state_to_dict(self, state) -> dict:
        """Convert a WorkflowState object to a dict suitable for graph execution.

        Args:
            state: A WorkflowState instance.

        Returns:
            A dictionary representation of the state.
        """
        return {
            "ticket": getattr(state, "ticket", {}),
            "context": getattr(state, "context", {}),
            "modified_files": getattr(state, "modified_files", []),
            "plan": getattr(state, "plan", {}),
            "logs": getattr(state, "logs", []),
            "evidence": getattr(state, "evidence", []),
            "errors": getattr(state, "errors", []),
            "metrics": getattr(state, "metrics", {}),
            "metadata": getattr(state, "metadata", {}),
            "workspace": getattr(state, "workspace", {}),
            "pending_question": getattr(state, "pending_question", None),
        }
