"""WorkCommand use case for initiating a full workflow execution."""

from concurrent.futures import ThreadPoolExecutor

from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.application.orchestrator.graph_builder import GraphBuilder
from autopilot.domain.entities.config import Config
from autopilot.domain.entities.run_record import RunRecord
from autopilot.domain.interfaces.serializer import SerializerInterface


class WorkCommand:
    """Use case that initiates a full work workflow for a given ticket.

    Creates a fresh WorkflowState, builds the work graph, executes
    the workflow, and returns a RunRecord with the execution results.
    """

    def __init__(
        self,
        engine: OrchestrationEngine,
        graph_builder: GraphBuilder,
        config: Config,
        serializer: SerializerInterface,
        approval_gate=None,
        workspace_manager=None,
        ticket_loader=None,
    ) -> None:
        """Initialize the WorkCommand use case.

        Args:
            engine: The orchestration engine for executing graphs.
            graph_builder: Builder for constructing workflow graphs.
            config: Application configuration.
            serializer: Serializer for state persistence.
            approval_gate: Optional ApprovalGate; its skip_all flag is set
                when approve=True is passed to execute().
        """
        self._engine = engine
        self._graph_builder = graph_builder
        self._config = config
        self._serializer = serializer
        self._approval_gate = approval_gate
        self._workspace_manager = workspace_manager
        self._ticket_loader = ticket_loader

    def execute(
        self,
        ticket_id: str,
        ticket_title: str = "",
        mode: str = "live",
        approve: bool = False,
    ) -> RunRecord:
        """Execute one ticket while serializing runs for that ticket."""
        if self._workspace_manager is not None:
            with self._workspace_manager.execution_lock(ticket_id):
                return self._execute(ticket_id, ticket_title, mode, approve)
        return self._execute(ticket_id, ticket_title, mode, approve)

    def _execute(
        self,
        ticket_id: str,
        ticket_title: str = "",
        mode: str = "live",
        approve: bool = False,
    ) -> RunRecord:
        """Execute a full work workflow for the given ticket.

        Creates a fresh initial state with the ticket ID set, builds the
        work graph, runs execution through the orchestration engine, and
        returns a RunRecord with the execution results.

        Args:
            ticket_id: The identifier of the ticket to process.
            ticket_title: Title of the Jira ticket.
            mode: Execution mode ("live", "dry-run").
            approve: When True, auto-approves every human-in-the-loop gate.

        Returns:
            RunRecord with the execution results.
        """
        if approve and self._approval_gate is not None:
            self._approval_gate.skip_all(True)
        run_record = self._engine.create_run_record(
            ticket_id=ticket_id,
            ticket_title=ticket_title,
            mode=mode,
        )

        workspace_data = {}
        initial_ticket = {"id": ticket_id}
        if ticket_title:
            initial_ticket["title"] = ticket_title
        if self._workspace_manager is not None:
            if self._ticket_loader is not None:
                loaded_ticket = self._ticket_loader(ticket_id)
                if isinstance(loaded_ticket, dict):
                    initial_ticket = {**loaded_ticket, "id": ticket_id, "_prefetched": True}
            try:
                workspace = self._workspace_manager.create_workspace(
                    initial_ticket,
                    run_id=run_record.run_id,
                    agent_id="workflow",
                )
            except Exception as exc:
                run_record.mark_failed(str(exc))
                self._engine.update_run_record(run_record)
                raise
            workspace_data = workspace.to_dict()
            run_record.workspace = workspace_data
            self._engine.update_run_record(run_record)

        initial_state = {
            "ticket": initial_ticket,
            "context": {},
            "modified_files": [],
            "plan": {},
            "logs": [],
            "evidence": [],
            "errors": [],
            "metrics": {},
            "metadata": {"mode": mode, "test_attempts": 0},
            "workspace": workspace_data,
        }

        graph = self._graph_builder.build_work_graph()

        self._engine.execute(graph, initial_state, run_record=run_record)

        return run_record

    def execute_many(
        self,
        ticket_ids: list[str],
        mode: str = "live",
        approve: bool = False,
        max_workers: int | None = None,
    ) -> dict[str, RunRecord]:
        """Execute independent tickets concurrently in isolated worktrees."""
        if not ticket_ids:
            return {}

        def run(ticket_id: str) -> tuple[str, RunRecord]:
            return ticket_id, self.execute(ticket_id, mode=mode, approve=approve)

        with ThreadPoolExecutor(max_workers=max_workers or len(ticket_ids)) as executor:
            results = executor.map(run, ticket_ids)
            return dict(results)
