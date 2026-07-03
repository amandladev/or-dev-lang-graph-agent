"""ResumeCommand use case for resuming a paused or failed workflow."""

import uuid

from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.application.orchestrator.graph_builder import GraphBuilder, WORK_GRAPH_NODES
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

    def execute(self) -> str:
        """Resume a previously paused or failed workflow.

        1. Load the most recent persisted state via serializer.load()
        2. Inspect the logs to find the last agent with status "success"
        3. Determine the next node in the graph (the node after the last successful one)
        4. Build a resume graph starting from that node
        5. Execute the graph via engine.execute()
        6. Return a unique execution ID

        Returns:
            A unique execution ID (UUID) for tracking this resumed workflow run.
        """
        # 1. Load the most recent persisted state
        state_filepath = f"{self._config.workspace_location}/.autopilot_state.json"
        restored_state = self._serializer.load(state_filepath)

        # 2. Convert WorkflowState to a state dict for graph execution
        state_dict = self._state_to_dict(restored_state)

        # 3. Identify the resume point from execution logs
        resume_from = self._find_resume_node(state_dict.get("logs", []))

        # 4. Build a resume graph starting from the identified node
        graph = self._graph_builder.build_resume_graph(resume_from)

        # 5. Execute the graph via engine
        self._engine.execute(graph, state_dict)

        # 6. Return a unique execution ID
        execution_id = str(uuid.uuid4())
        return execution_id

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
        }
