"""Property 6: Agent input extraction.

Validates: Requirements 2.2

For any agent with a declared input_schema and for any WorkflowState containing
additional fields beyond the schema, the OrchestrationEngine's node wrapper
extracts and passes only the fields declared in the agent's input_schema —
no extra fields.
"""

from typing import Any
from unittest.mock import MagicMock

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from autopilot.application.orchestrator.engine import GraphState, OrchestrationEngine
from autopilot.application.orchestrator.retry_policy import RetryPolicy

# ---------------------------------------------------------------------------
# All possible fields in GraphState
# ---------------------------------------------------------------------------

GRAPH_STATE_FIELDS = list(GraphState.__annotations__.keys())
# ['ticket', 'context', 'modified_files', 'plan', 'logs', 'evidence', 'errors', 'metrics', 'metadata']


# ---------------------------------------------------------------------------
# Mock agent that records what input it receives
# ---------------------------------------------------------------------------


class RecordingAgent:
    """An agent that records the exact state dict passed to execute()."""

    def __init__(self, name: str, input_schema: dict[str, type]) -> None:
        self._name = name
        self._input_schema = input_schema
        self.received_state: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Recording agent for testing input extraction"

    @property
    def input_schema(self) -> dict[str, type]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, type]:
        return {"metrics": dict}

    def execute(
        self,
        state: dict[str, Any],
        memory_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.received_state = dict(state)
        return {"metrics": {"completed": True}}


# ---------------------------------------------------------------------------
# Mock dependencies
# ---------------------------------------------------------------------------


def create_mock_registry(agent: RecordingAgent) -> MagicMock:
    """Create a mock agent registry that returns the given agent."""
    registry = MagicMock()
    registry.get.return_value = agent
    return registry


def create_mock_logger() -> MagicMock:
    """Create a mock logger with required methods."""
    logger = MagicMock()
    logger.log_agent_start = MagicMock()
    logger.log_agent_completion = MagicMock()
    return logger


def create_mock_serializer() -> MagicMock:
    """Create a mock serializer."""
    serializer = MagicMock()
    serializer.persist = MagicMock()
    return serializer


def create_mock_config() -> MagicMock:
    """Create a mock config object."""
    config = MagicMock()
    config.workspace_location = "/tmp/test"
    return config


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy: generate a non-empty subset of GraphState fields for an agent's input_schema
input_schema_keys_strategy = st.lists(
    st.sampled_from(GRAPH_STATE_FIELDS),
    min_size=1,
    max_size=len(GRAPH_STATE_FIELDS) - 1,  # Leave room for at least one extra field
    unique=True,
)

# Strategy: generate values for state fields
state_value_strategy = st.one_of(
    st.dictionaries(st.text(min_size=1, max_size=10), st.text(max_size=20), max_size=5),
    st.lists(st.text(max_size=20), max_size=5),
)


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    schema_keys=input_schema_keys_strategy,
    data=st.data(),
)
def test_node_extracts_only_input_schema_fields(
    schema_keys: list[str],
    data: st.DataObject,
):
    """**Validates: Requirements 2.2**

    Property 6: For any agent with a declared input_schema and for any
    WorkflowState containing additional fields beyond the schema, the
    OrchestrationEngine's node wrapper extracts and passes only the fields
    declared in the agent's input_schema — no extra fields.
    """
    # Determine extra fields not in the agent's input_schema
    extra_fields = [f for f in GRAPH_STATE_FIELDS if f not in schema_keys]
    assume(len(extra_fields) > 0)  # Must have at least one extra field

    # Build the input_schema as a dict mapping field names to types
    input_schema = {k: dict for k in schema_keys}

    # Create a recording agent with the generated input_schema
    agent = RecordingAgent(name="test_agent", input_schema=input_schema)

    # Build a full state dict with values for ALL fields (schema + extra)
    state: dict[str, Any] = {}
    for field in GRAPH_STATE_FIELDS:
        if field == "modified_files":
            state[field] = data.draw(st.lists(st.text(max_size=10), max_size=3))
        elif field in ("logs", "evidence", "errors"):
            state[field] = data.draw(st.lists(
                st.dictionaries(st.text(min_size=1, max_size=10), st.text(max_size=10), max_size=3),
                max_size=3,
            ))
        else:
            state[field] = data.draw(
                st.dictionaries(st.text(min_size=1, max_size=10), st.text(max_size=10), max_size=3)
            )

    # Wire up mocks
    registry = create_mock_registry(agent)
    logger = create_mock_logger()
    serializer = create_mock_serializer()
    config = create_mock_config()
    retry_policy = RetryPolicy(max_retries=0, base_delay=0.0, backoff_multiplier=1.0)

    engine = OrchestrationEngine(
        agent_registry=registry,
        serializer=serializer,
        logger=logger,
        retry_policy=retry_policy,
        config=config,
    )

    # Create the node function and invoke it with the full state
    node_fn = engine.create_agent_node("test_agent")
    node_fn(state)

    # Verify: the agent received ONLY the fields declared in input_schema
    assert agent.received_state is not None, "Agent execute() was never called"

    received_keys = set(agent.received_state.keys())
    expected_keys = set(schema_keys)

    assert received_keys == expected_keys, (
        f"Agent received keys {received_keys} but expected only {expected_keys}. "
        f"Extra keys passed: {received_keys - expected_keys}"
    )

    # Additionally verify no extra fields leaked through
    for extra_field in extra_fields:
        assert extra_field not in agent.received_state, (
            f"Extra field '{extra_field}' was passed to agent but is not in input_schema"
        )


@settings(max_examples=100)
@given(
    schema_keys=input_schema_keys_strategy,
    data=st.data(),
)
def test_node_passes_correct_values_for_schema_fields(
    schema_keys: list[str],
    data: st.DataObject,
):
    """**Validates: Requirements 2.2**

    Property 6: The extracted fields contain the correct values from the
    WorkflowState (not None or empty defaults), confirming the extraction
    maps the right values to the right keys.
    """
    # Build the input_schema
    input_schema = {k: dict for k in schema_keys}

    # Create a recording agent
    agent = RecordingAgent(name="value_agent", input_schema=input_schema)

    # Build a full state with distinct values per field
    state: dict[str, Any] = {}
    for field in GRAPH_STATE_FIELDS:
        if field == "modified_files":
            state[field] = data.draw(st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=3))
        elif field in ("logs", "evidence", "errors"):
            state[field] = data.draw(st.lists(
                st.dictionaries(st.text(min_size=1, max_size=10), st.text(max_size=10), min_size=1, max_size=3),
                min_size=1,
                max_size=3,
            ))
        else:
            state[field] = data.draw(
                st.dictionaries(st.text(min_size=1, max_size=10), st.text(max_size=10), min_size=1, max_size=3)
            )

    # Wire up mocks
    registry = create_mock_registry(agent)
    logger = create_mock_logger()
    serializer = create_mock_serializer()
    config = create_mock_config()
    retry_policy = RetryPolicy(max_retries=0, base_delay=0.0, backoff_multiplier=1.0)

    engine = OrchestrationEngine(
        agent_registry=registry,
        serializer=serializer,
        logger=logger,
        retry_policy=retry_policy,
        config=config,
    )

    # Create and invoke the node
    node_fn = engine.create_agent_node("value_agent")
    node_fn(state)

    # Verify values match what was in the original state
    assert agent.received_state is not None, "Agent execute() was never called"

    for key in schema_keys:
        assert agent.received_state[key] == state[key], (
            f"Value mismatch for field '{key}': "
            f"agent received {agent.received_state[key]!r} "
            f"but state had {state[key]!r}"
        )
