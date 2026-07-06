"""WorkCommand use case for initiating a full workflow execution."""

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
    ) -> None:
        """Initialize the WorkCommand use case.

        Args:
            engine: The orchestration engine for executing graphs.
            graph_builder: Builder for constructing workflow graphs.
            config: Application configuration.
            serializer: Serializer for state persistence.
        """
        self._engine = engine
        self._graph_builder = graph_builder
        self._config = config
        self._serializer = serializer

    def execute(self, ticket_id: str, ticket_title: str = "", mode: str = "live") -> RunRecord:
        """Execute a full work workflow for the given ticket.

        Creates a fresh initial state with the ticket ID set, builds the
        work graph, runs execution through the orchestration engine, and
        returns a RunRecord with the execution results.

        Args:
            ticket_id: The identifier of the ticket to process.
            ticket_title: Title of the Jira ticket.
            mode: Execution mode ("live", "dry-run").

        Returns:
            RunRecord with the execution results.
        """
        # 1. Create RunRecord for tracking this execution
        run_record = self._engine.create_run_record(
            ticket_id=ticket_id,
            ticket_title=ticket_title,
            mode=mode,
        )

        # 2. Create a fresh initial state with ticket.id set, all other fields empty/default
        initial_state = {
            "ticket": {"id": ticket_id},
            "context": {},
            "modified_files": [],
            "plan": {},
            "logs": [],
            "evidence": [],
            "errors": [],
            "metrics": {},
            "metadata": {},
        }

        # 3. Build the work graph
        graph = self._graph_builder.build_work_graph()

        # 4. Execute the graph via engine
        self._engine.execute(graph, initial_state, run_record=run_record)

        # 5. Return the run record
        return run_record
