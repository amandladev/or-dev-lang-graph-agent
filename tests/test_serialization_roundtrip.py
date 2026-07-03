"""Property 1: WorkflowState serialization round-trip.

**Validates: Requirements 5.4, 12.6, 13.1, 13.2, 13.3**

For any valid WorkflowState object (with arbitrary values in ticket, context,
modified_files, plan, logs, evidence, errors, metrics, and metadata fields),
serializing to JSON and then deserializing SHALL produce an object with
field-by-field equality to the original.
"""

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.domain.entities.workflow_state import WorkflowState
from autopilot.domain.value_objects.error_record import ErrorRecord, ErrorType
from autopilot.domain.value_objects.evidence import EvidenceItem
from autopilot.domain.value_objects.log_entry import LogEntry, StepStatus
from autopilot.infrastructure.adapters.json_serializer import JSONSerializer


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# JSON-safe text: avoid null bytes and surrogates that don't survive JSON round-trip
safe_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # exclude surrogates
        blacklist_characters=("\x00",),
    ),
    min_size=0,
    max_size=50,
)

# JSON-safe dictionary keys (must be non-empty strings for JSON object keys)
safe_key = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters=("\x00",),
    ),
    min_size=1,
    max_size=20,
)

# Primitive values that survive JSON round-trip
json_primitive = st.one_of(
    safe_text,
    st.integers(min_value=-(2**53), max_value=2**53),
    st.booleans(),
)

# Ticket: dict with string keys and primitive values
ticket_strategy = st.dictionaries(
    keys=safe_key,
    values=json_primitive,
    max_size=10,
)

# Context: dict with string keys and string values
context_strategy = st.dictionaries(
    keys=safe_key,
    values=safe_text,
    max_size=10,
)

# Modified files: list of strings
modified_files_strategy = st.lists(safe_text, max_size=10)

# Plan: dict with string keys and values that are either strings or lists of strings
plan_strategy = st.dictionaries(
    keys=safe_key,
    values=st.one_of(safe_text, st.lists(safe_text, max_size=5)),
    max_size=10,
)

# Datetimes that survive ISO format round-trip (avoid sub-microsecond precision issues)
safe_datetime = st.datetimes(
    min_value=datetime(1900, 1, 1),
    max_value=datetime(2100, 12, 31, 23, 59, 59),
)

# StepStatus enum
step_status_strategy = st.sampled_from(list(StepStatus))

# LogEntry strategy
log_entry_strategy = st.builds(
    LogEntry,
    agent_name=safe_text,
    start_time=safe_datetime,
    end_time=safe_datetime,
    elapsed_ms=st.integers(min_value=0, max_value=10_000_000),
    input_data=st.dictionaries(safe_key, json_primitive, max_size=5),
    output_data=st.dictionaries(safe_key, json_primitive, max_size=5),
    status=step_status_strategy,
)

# Logs: list of LogEntry
logs_strategy = st.lists(log_entry_strategy, max_size=5)

# EvidenceItem strategy
evidence_item_strategy = st.builds(
    EvidenceItem,
    type=safe_text,
    description=safe_text,
    path=st.one_of(st.none(), safe_text),
    data=st.one_of(st.none(), st.dictionaries(safe_key, json_primitive, max_size=5)),
)

# Evidence: list of EvidenceItem
evidence_strategy = st.lists(evidence_item_strategy, max_size=5)

# ErrorType enum
error_type_strategy = st.sampled_from(list(ErrorType))

# ErrorRecord strategy
error_record_strategy = st.builds(
    ErrorRecord,
    error_type=error_type_strategy,
    description=safe_text,
    agent_name=safe_text,
    attempt_count=st.integers(min_value=0, max_value=100),
    exception_class=safe_text,
)

# Errors: list of ErrorRecord
errors_strategy = st.lists(error_record_strategy, max_size=5)

# Metrics: dict with string keys and integer values
metrics_strategy = st.dictionaries(
    keys=safe_key,
    values=st.integers(min_value=-(2**53), max_value=2**53),
    max_size=10,
)

# Metadata: dict with string keys and mixed primitive values
metadata_strategy = st.dictionaries(
    keys=safe_key,
    values=json_primitive,
    max_size=10,
)

# Full WorkflowState strategy
workflow_state_strategy = st.builds(
    WorkflowState,
    ticket=ticket_strategy,
    context=context_strategy,
    modified_files=modified_files_strategy,
    plan=plan_strategy,
    logs=logs_strategy,
    evidence=evidence_strategy,
    errors=errors_strategy,
    metrics=metrics_strategy,
    metadata=metadata_strategy,
)


# ---------------------------------------------------------------------------
# Property-Based Test
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(state=workflow_state_strategy)
def test_workflow_state_serialization_round_trip(state: WorkflowState):
    """**Validates: Requirements 5.4, 12.6, 13.1, 13.2, 13.3**

    Property 1: For any valid WorkflowState, serializing to JSON and then
    deserializing produces an object with field-by-field equality to the original.
    """
    serializer = JSONSerializer()

    json_str = serializer.serialize(state)
    restored = serializer.deserialize(json_str)

    # Field-by-field equality
    assert restored.ticket == state.ticket, (
        f"ticket mismatch: {restored.ticket!r} != {state.ticket!r}"
    )
    assert restored.context == state.context, (
        f"context mismatch: {restored.context!r} != {state.context!r}"
    )
    assert restored.modified_files == state.modified_files, (
        f"modified_files mismatch: {restored.modified_files!r} != {state.modified_files!r}"
    )
    assert restored.plan == state.plan, (
        f"plan mismatch: {restored.plan!r} != {state.plan!r}"
    )
    assert restored.logs == state.logs, (
        f"logs mismatch: {restored.logs!r} != {state.logs!r}"
    )
    assert restored.evidence == state.evidence, (
        f"evidence mismatch: {restored.evidence!r} != {state.evidence!r}"
    )
    assert restored.errors == state.errors, (
        f"errors mismatch: {restored.errors!r} != {state.errors!r}"
    )
    assert restored.metrics == state.metrics, (
        f"metrics mismatch: {restored.metrics!r} != {state.metrics!r}"
    )
    assert restored.metadata == state.metadata, (
        f"metadata mismatch: {restored.metadata!r} != {state.metadata!r}"
    )

    # Overall equality
    assert restored == state
