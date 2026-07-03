"""Property 7: State merge semantics.

**Validates: Requirements 5.2**

For any WorkflowState and for any agent output, merging SHALL append values to
list fields (modified_files, logs, evidence, errors) and overwrite scalar/object
fields (ticket, context, plan, metrics, metadata). After merge, list fields SHALL
equal the original list concatenated with the new items.
"""

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.application.orchestrator.engine import append_list, overwrite, OrchestrationEngine
from autopilot.application.orchestrator.retry_policy import RetryPolicy


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Simple JSON-compatible values for scalar/object fields
json_primitive_strategy = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(min_size=0, max_size=20),
)

# Simple dict strategy for scalar/object fields (ticket, context, plan, metrics, metadata)
simple_dict_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=10),
    values=json_primitive_strategy,
    min_size=0,
    max_size=5,
)

# List of strings for modified_files
string_list_strategy = st.lists(
    st.text(min_size=1, max_size=30),
    min_size=0,
    max_size=10,
)

# List of dicts for logs, evidence, errors
dict_list_strategy = st.lists(
    simple_dict_strategy,
    min_size=0,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Property-Based Tests: append_list reducer
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    existing=string_list_strategy,
    new=string_list_strategy,
)
def test_append_list_concatenates_string_lists(existing: list[str], new: list[str]):
    """**Validates: Requirements 5.2**

    Property 7: The append_list reducer SHALL produce a list equal to
    existing + new (concatenation).
    """
    result = append_list(existing, new)
    assert result == existing + new


@settings(max_examples=100)
@given(
    existing=dict_list_strategy,
    new=dict_list_strategy,
)
def test_append_list_concatenates_dict_lists(existing: list[dict], new: list[dict]):
    """**Validates: Requirements 5.2**

    Property 7: The append_list reducer SHALL produce a list equal to
    existing + new for lists of dicts (logs, evidence, errors).
    """
    result = append_list(existing, new)
    assert result == existing + new


@settings(max_examples=100)
@given(
    existing=string_list_strategy,
    new=string_list_strategy,
)
def test_append_list_preserves_original_order(existing: list[str], new: list[str]):
    """**Validates: Requirements 5.2**

    Property 7: After append, the first len(existing) elements SHALL equal
    the original list exactly, and the remaining elements SHALL equal the new list.
    """
    result = append_list(existing, new)
    assert result[: len(existing)] == existing
    assert result[len(existing) :] == new


# ---------------------------------------------------------------------------
# Property-Based Tests: overwrite reducer
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    existing=simple_dict_strategy,
    new=simple_dict_strategy,
)
def test_overwrite_returns_new_value(existing: dict, new: dict):
    """**Validates: Requirements 5.2**

    Property 7: The overwrite reducer SHALL return the new value, discarding
    the existing value entirely.
    """
    result = overwrite(existing, new)
    assert result == new


@settings(max_examples=100)
@given(
    existing=json_primitive_strategy,
    new=json_primitive_strategy,
)
def test_overwrite_returns_new_for_any_value(existing: Any, new: Any):
    """**Validates: Requirements 5.2**

    Property 7: The overwrite reducer SHALL return the new value for any
    type of scalar input.
    """
    result = overwrite(existing, new)
    assert result is new


# ---------------------------------------------------------------------------
# Property-Based Tests: OrchestrationEngine._merge_state
# ---------------------------------------------------------------------------


class _FakeRegistry:
    """Minimal fake for engine construction."""
    pass


class _FakeSerializer:
    """Minimal fake for engine construction."""
    pass


class _FakeLogger:
    """Minimal fake for engine construction."""
    pass


class _FakeConfig:
    """Minimal fake for engine construction."""
    workspace_location = "/tmp"


def _create_engine() -> OrchestrationEngine:
    """Create an OrchestrationEngine instance for testing _merge_state."""
    retry_policy = RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
    return OrchestrationEngine(
        agent_registry=_FakeRegistry(),
        serializer=_FakeSerializer(),
        logger=_FakeLogger(),
        retry_policy=retry_policy,
        config=_FakeConfig(),
    )


@settings(max_examples=100)
@given(
    existing_files=string_list_strategy,
    new_files=string_list_strategy,
    existing_logs=dict_list_strategy,
    new_logs=dict_list_strategy,
    existing_evidence=dict_list_strategy,
    new_evidence=dict_list_strategy,
    existing_errors=dict_list_strategy,
    new_errors=dict_list_strategy,
)
def test_merge_state_appends_list_fields(
    existing_files: list[str],
    new_files: list[str],
    existing_logs: list[dict],
    new_logs: list[dict],
    existing_evidence: list[dict],
    new_evidence: list[dict],
    existing_errors: list[dict],
    new_errors: list[dict],
):
    """**Validates: Requirements 5.2**

    Property 7: For any WorkflowState and agent output, merging SHALL append
    values to list fields (modified_files, logs, evidence, errors). After merge,
    list fields SHALL equal the original list concatenated with the new items.
    """
    engine = _create_engine()

    current_state = {
        "ticket": {"id": "T-1"},
        "context": {},
        "modified_files": existing_files,
        "plan": {},
        "logs": existing_logs,
        "evidence": existing_evidence,
        "errors": existing_errors,
        "metrics": {},
        "metadata": {},
    }

    agent_output = {
        "modified_files": new_files,
        "logs": new_logs,
        "evidence": new_evidence,
        "errors": new_errors,
    }

    merged = engine._merge_state(current_state, agent_output)

    assert merged["modified_files"] == existing_files + new_files
    assert merged["logs"] == existing_logs + new_logs
    assert merged["evidence"] == existing_evidence + new_evidence
    assert merged["errors"] == existing_errors + new_errors


@settings(max_examples=100)
@given(
    existing_ticket=simple_dict_strategy,
    new_ticket=simple_dict_strategy,
    existing_context=simple_dict_strategy,
    new_context=simple_dict_strategy,
    existing_plan=simple_dict_strategy,
    new_plan=simple_dict_strategy,
    existing_metrics=simple_dict_strategy,
    new_metrics=simple_dict_strategy,
    existing_metadata=simple_dict_strategy,
    new_metadata=simple_dict_strategy,
)
def test_merge_state_overwrites_scalar_fields(
    existing_ticket: dict,
    new_ticket: dict,
    existing_context: dict,
    new_context: dict,
    existing_plan: dict,
    new_plan: dict,
    existing_metrics: dict,
    new_metrics: dict,
    existing_metadata: dict,
    new_metadata: dict,
):
    """**Validates: Requirements 5.2**

    Property 7: For any WorkflowState and agent output, merging SHALL overwrite
    scalar/object fields (ticket, context, plan, metrics, metadata) with the
    new values from the agent output.
    """
    engine = _create_engine()

    current_state = {
        "ticket": existing_ticket,
        "context": existing_context,
        "modified_files": [],
        "plan": existing_plan,
        "logs": [],
        "evidence": [],
        "errors": [],
        "metrics": existing_metrics,
        "metadata": existing_metadata,
    }

    agent_output = {
        "ticket": new_ticket,
        "context": new_context,
        "plan": new_plan,
        "metrics": new_metrics,
        "metadata": new_metadata,
    }

    merged = engine._merge_state(current_state, agent_output)

    assert merged["ticket"] == new_ticket
    assert merged["context"] == new_context
    assert merged["plan"] == new_plan
    assert merged["metrics"] == new_metrics
    assert merged["metadata"] == new_metadata


@settings(max_examples=100)
@given(
    existing_files=string_list_strategy,
    new_files=string_list_strategy,
    existing_ticket=simple_dict_strategy,
    new_ticket=simple_dict_strategy,
)
def test_merge_state_combined_append_and_overwrite(
    existing_files: list[str],
    new_files: list[str],
    existing_ticket: dict,
    new_ticket: dict,
):
    """**Validates: Requirements 5.2**

    Property 7: When an agent output contains both list fields and scalar fields,
    list fields use append semantics and scalar fields use overwrite semantics
    simultaneously.
    """
    engine = _create_engine()

    current_state = {
        "ticket": existing_ticket,
        "context": {},
        "modified_files": existing_files,
        "plan": {},
        "logs": [],
        "evidence": [],
        "errors": [],
        "metrics": {},
        "metadata": {},
    }

    agent_output = {
        "ticket": new_ticket,
        "modified_files": new_files,
    }

    merged = engine._merge_state(current_state, agent_output)

    # List field: appended
    assert merged["modified_files"] == existing_files + new_files
    # Scalar field: overwritten
    assert merged["ticket"] == new_ticket
    # Unchanged fields preserved
    assert merged["context"] == {}
    assert merged["plan"] == {}


@settings(max_examples=100)
@given(
    existing_files=string_list_strategy,
    existing_ticket=simple_dict_strategy,
)
def test_merge_state_empty_output_preserves_state(
    existing_files: list[str],
    existing_ticket: dict,
):
    """**Validates: Requirements 5.2**

    Property 7: When the agent output is empty, the merged state SHALL equal
    the original state (no fields altered).
    """
    engine = _create_engine()

    current_state = {
        "ticket": existing_ticket,
        "context": {"key": "value"},
        "modified_files": existing_files,
        "plan": {"steps": []},
        "logs": [{"entry": "1"}],
        "evidence": [],
        "errors": [],
        "metrics": {"total": 100},
        "metadata": {"version": "1.0"},
    }

    agent_output: dict[str, Any] = {}

    merged = engine._merge_state(current_state, agent_output)

    assert merged == current_state
