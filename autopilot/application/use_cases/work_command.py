"""WorkCommand use case for initiating a full workflow execution."""

import uuid

from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.application.orchestrator.graph_builder import GraphBuilder
from autopilot.domain.entities.config import Config
from autopilot.domain.interfaces.serializer import SerializerInterface


class WorkCommand:
    """Use case that initiates a full work workflow for a given ticket.

    Creates a fresh WorkflowState, builds the work graph, executes
    the workflow, and returns a unique execution ID.
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

    def execute(self, ticket_id: str) -> str:
        """Execute a full work workflow for the given ticket.

        Creates a fresh initial state with the ticket ID set, builds the
        work graph, runs execution through the orchestration engine, and
        returns a unique execution ID.

        Args:
            ticket_id: The identifier of the ticket to process.

        Returns:
            A unique execution ID (UUID) for tracking this workflow run.
        """
        # 1. Create a fresh initial state with ticket.id set, all other fields empty/default
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

        # 2. Build the work graph
        graph = self._graph_builder.build_work_graph()

        # 3. Execute the graph via engine
        self._engine.execute(graph, initial_state)

        # 4. Generate and return a unique execution ID
        execution_id = str(uuid.uuid4())
        return execution_id
