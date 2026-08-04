"""Tests for the Agent_Node retry loop and OrchestrationEngine.execute() verdict logic.

Covers Requirement 1 (retry loop) and Requirement 2 (RunRecord verdict) of
core-orchestration-test-coverage.
"""

import itertools
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.application.orchestrator.retry_policy import RetryPolicy
from autopilot.domain.entities.run_record import RunRecord
from autopilot.domain.value_objects.exceptions import ToolTimeoutError

# ---------------------------------------------------------------------------
# Shared fakes (file-local, matching tests/test_state_merge.py convention)
# ---------------------------------------------------------------------------


class _FakeRegistry:
    """Minimal fake agent registry; `.get(name)` returns a preset agent."""

    def __init__(self, agent) -> None:
        self._agent = agent

    def get(self, name: str):
        return self._agent


class _FakeSerializer:
    """Minimal fake serializer used only to satisfy engine construction."""

    def persist(self, state, filepath) -> None:
        pass


class _FakeLogger:
    """Minimal fake logger that swallows all calls."""

    def log_agent_start(self, *args, **kwargs) -> None:
        pass

    def log_agent_completion(self, *args, **kwargs) -> None:
        pass

    def log_retry(self, *args, **kwargs) -> None:
        pass

    def log_warning(self, *args, **kwargs) -> None:
        pass


class _FakeConfig:
    workspace_location = "/tmp"


def _make_agent(input_schema=None, side_effect=None):
    """Build a MagicMock agent with an input_schema and execute side_effect."""
    agent = MagicMock()
    agent.input_schema = input_schema if input_schema is not None else {}
    agent.execute = MagicMock(side_effect=side_effect)
    return agent


def _make_engine(agent, run_record_store=None, max_retries=3):
    retry_policy = RetryPolicy(max_retries=max_retries, base_delay=1.0, backoff_multiplier=2.0)
    return OrchestrationEngine(
        agent_registry=_FakeRegistry(agent),
        serializer=_FakeSerializer(),
        logger=_FakeLogger(),
        retry_policy=retry_policy,
        config=_FakeConfig(),
        run_record_store=run_record_store,
    )


# ---------------------------------------------------------------------------
# Property 1: Non-retryable exceptions stop the retry loop immediately
# Validates: Requirements 1.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    message=st.text(max_size=50),
    agent_name=st.text(min_size=1, max_size=20),
)
@patch("autopilot.application.orchestrator.engine.time.sleep")
def test_non_retryable_exception_stops_retry_loop_immediately(
    mock_sleep, message: str, agent_name: str
):
    """Feature: core-orchestration-test-coverage, Property 1: Non-retryable
    exceptions stop the retry loop immediately.

    **Validates: Requirements 1.1**
    """
    exc = ValueError(message)  # not in RETRYABLE_EXCEPTIONS -> NON_RETRYABLE
    agent = _make_agent(side_effect=exc)
    engine = _make_engine(agent)
    node = engine.create_agent_node(agent_name)

    with pytest.raises(ValueError) as exc_info:
        node({})

    assert exc_info.value is exc
    assert agent.execute.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Property 2: Retryable exceptions on every attempt exhaust the configured
# retry budget
# Validates: Requirements 1.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(message=st.text(max_size=50))
@patch("autopilot.application.orchestrator.engine.time.sleep")
def test_retryable_exception_every_attempt_exhausts_retry_budget(mock_sleep, message: str):
    """Feature: core-orchestration-test-coverage, Property 2: Retryable
    exceptions on every attempt exhaust the configured retry budget.

    **Validates: Requirements 1.2**
    """
    exc = TimeoutError(message)  # in RETRYABLE_EXCEPTIONS
    agent = _make_agent(side_effect=itertools.repeat(exc))
    engine = _make_engine(agent, max_retries=3)
    node = engine.create_agent_node("some_agent")

    with pytest.raises(TimeoutError) as exc_info:
        node({})

    assert exc_info.value is exc
    assert agent.execute.call_count == 4  # max_retries + 1


# ---------------------------------------------------------------------------
# Property 3: A retryable failure followed by success returns the successful
# output
# Validates: Requirements 1.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(num_failures=st.integers(min_value=0, max_value=3))
@patch("autopilot.application.orchestrator.engine.time.sleep")
def test_retryable_failure_then_success_returns_output(mock_sleep, num_failures: int):
    """Feature: core-orchestration-test-coverage, Property 3: A retryable
    failure followed by success returns the successful output.

    **Validates: Requirements 1.3**
    """
    success_output = {"result": "ok"}
    side_effects = [ConnectionError("boom")] * num_failures + [success_output]
    agent = _make_agent(side_effect=side_effects)
    engine = _make_engine(agent, max_retries=3)
    node = engine.create_agent_node("some_agent")

    result = node({})

    assert result == success_output
    assert agent.execute.call_count == num_failures + 1
    assert mock_sleep.call_count == num_failures


# ---------------------------------------------------------------------------
# Property 4: Retry backoff delay matches RetryPolicy.get_delay for the
# current attempt
# Validates: Requirements 1.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(num_failures=st.integers(min_value=1, max_value=3))
@patch("autopilot.application.orchestrator.engine.time.sleep")
def test_sleep_called_with_get_delay_of_current_attempt(mock_sleep, num_failures: int):
    """Feature: core-orchestration-test-coverage, Property 4: Retry backoff
    delay matches RetryPolicy.get_delay for the current attempt.

    **Validates: Requirements 1.4**
    """
    success_output = {"result": "ok"}
    side_effects = [ConnectionError("boom")] * num_failures + [success_output]
    agent = _make_agent(side_effect=side_effects)
    retry_policy = RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
    engine = OrchestrationEngine(
        agent_registry=_FakeRegistry(agent),
        serializer=_FakeSerializer(),
        logger=_FakeLogger(),
        retry_policy=retry_policy,
        config=_FakeConfig(),
    )
    node = engine.create_agent_node("some_agent")

    node({})

    expected_delays = [retry_policy.get_delay(attempt) for attempt in range(num_failures)]
    actual_delays = [call_args.args[0] for call_args in mock_sleep.call_args_list]
    assert actual_delays == expected_delays


# ---------------------------------------------------------------------------
# 1.5/1.6: Persisted error state example tests (fixed max_retries=3)
# Validates: Requirements 1.5, 1.6, 1.7
# ---------------------------------------------------------------------------


@patch("autopilot.application.orchestrator.engine.time.sleep")
def test_exhausted_retries_persists_error_record_with_attempt_count_four(mock_sleep):
    """**Validates: Requirements 1.5, 1.7**

    With max_retries fixed at 3, exhausting all retryable attempts SHALL
    persist an error state with attempt_count == 4 and exception_class
    equal to the raised exception's type name.
    """
    exc = ToolTimeoutError("timed out")
    agent = _make_agent(side_effect=itertools.repeat(exc))
    serializer = MagicMock()
    engine = OrchestrationEngine(
        agent_registry=_FakeRegistry(agent),
        serializer=serializer,
        logger=_FakeLogger(),
        retry_policy=RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0),
        config=_FakeConfig(),
    )
    node = engine.create_agent_node("some_agent")

    with pytest.raises(ToolTimeoutError):
        node({})

    assert serializer.persist.call_count == 1
    persisted_state = serializer.persist.call_args.args[0]
    persisted_error = persisted_state.errors[-1]
    assert persisted_error["attempt_count"] == 4
    assert persisted_error["exception_class"] == "ToolTimeoutError"


@patch("autopilot.application.orchestrator.engine.time.sleep")
def test_non_retryable_persists_error_record_with_attempt_count_one(mock_sleep):
    """**Validates: Requirements 1.6, 1.7**

    A non-retryable exception on the first attempt SHALL persist an error
    state with attempt_count == 1 and exception_class equal to the raised
    exception's type name, with no further attempts made.
    """
    exc = ValueError("bad config")
    agent = _make_agent(side_effect=exc)
    serializer = MagicMock()
    engine = OrchestrationEngine(
        agent_registry=_FakeRegistry(agent),
        serializer=serializer,
        logger=_FakeLogger(),
        retry_policy=RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0),
        config=_FakeConfig(),
    )
    node = engine.create_agent_node("some_agent")

    with pytest.raises(ValueError):
        node({})

    assert agent.execute.call_count == 1
    assert serializer.persist.call_count == 1
    persisted_state = serializer.persist.call_args.args[0]
    persisted_error = persisted_state.errors[-1]
    assert persisted_error["attempt_count"] == 1
    assert persisted_error["exception_class"] == "ValueError"


# ---------------------------------------------------------------------------
# Finding 14: unrecognized non-retryable exceptions are flagged distinctly
# from deliberately configured business errors (auth/config/schema).
# ---------------------------------------------------------------------------


@patch("autopilot.application.orchestrator.engine.time.sleep")
def test_unrecognized_exception_description_flagged_as_unclassified(mock_sleep):
    exc = ValueError("some unexpected bug")  # not declared in either policy set
    agent = _make_agent(side_effect=exc)
    serializer = MagicMock()
    engine = OrchestrationEngine(
        agent_registry=_FakeRegistry(agent),
        serializer=serializer,
        logger=_FakeLogger(),
        retry_policy=RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0),
        config=_FakeConfig(),
    )
    node = engine.create_agent_node("some_agent")

    with pytest.raises(ValueError):
        node({})

    persisted_error = serializer.persist.call_args.args[0].errors[-1]
    assert persisted_error["description"].startswith("[unclassified exception]")


@patch("autopilot.application.orchestrator.engine.time.sleep")
def test_recognized_non_retryable_exception_not_flagged_as_unclassified(mock_sleep):
    from autopilot.domain.value_objects.exceptions import ConfigurationError

    exc = ConfigurationError("missing vault_location")
    agent = _make_agent(side_effect=exc)
    serializer = MagicMock()
    engine = OrchestrationEngine(
        agent_registry=_FakeRegistry(agent),
        serializer=serializer,
        logger=_FakeLogger(),
        retry_policy=RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0),
        config=_FakeConfig(),
    )
    node = engine.create_agent_node("some_agent")

    with pytest.raises(ConfigurationError):
        node({})

    persisted_error = serializer.persist.call_args.args[0].errors[-1]
    assert not persisted_error["description"].startswith("[unclassified exception]")
    assert persisted_error["description"] == "missing vault_location"


# ---------------------------------------------------------------------------
# Property 5: Verdict reflects the pass/fail composition of test-result
# evidence
# Validates: Requirements 2.1, 2.2, 2.3
# ---------------------------------------------------------------------------


test_result_strategy = st.lists(
    st.tuples(
        st.text(min_size=1, max_size=10),
        st.booleans(),
    ),
    min_size=0,
    max_size=10,
)


def _build_evidence(entries: list[tuple[str, bool]]) -> list[dict]:
    evidence = []
    for label, passing in entries:
        result_text = f"PASS {label}" if passing else f"FAIL {label}"
        evidence.append({"type": "test_result", "result": result_text})
    return evidence


@settings(max_examples=100)
@given(entries=test_result_strategy)
def test_verdict_reflects_test_evidence_composition(entries: list[tuple[str, bool]]):
    """Feature: core-orchestration-test-coverage, Property 5: Verdict
    reflects the pass/fail composition of test-result evidence.

    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    evidence = _build_evidence(entries)
    graph = MagicMock()
    graph.invoke.return_value = {"evidence": evidence}
    engine = _make_engine(_make_agent())
    run_record = RunRecord()

    engine.execute(graph, {}, run_record=run_record)

    total = len(entries)
    passed = sum(1 for _, is_pass in entries if is_pass)
    failed = total - passed

    assert run_record.status == "completed"
    assert run_record.tests_executed == total
    assert run_record.tests_passed == passed
    assert run_record.tests_failed == failed
    if total == 0 or passed == total:
        assert run_record.verdict == "PASS"
    else:
        assert run_record.verdict == "FAIL"


# ---------------------------------------------------------------------------
# Property 6: A non-empty errors list always marks the run failed
# Validates: Requirements 2.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    errors=st.lists(
        st.dictionaries(st.text(max_size=10), st.text(max_size=10)), min_size=1, max_size=5
    ),
    entries=test_result_strategy,
)
def test_non_empty_errors_marks_run_failed(errors: list[dict], entries: list[tuple[str, bool]]):
    """Feature: core-orchestration-test-coverage, Property 6: A non-empty
    errors list always marks the run failed.

    **Validates: Requirements 2.4**
    """
    evidence = _build_evidence(entries)
    graph = MagicMock()
    graph.invoke.return_value = {"evidence": evidence, "errors": errors}
    engine = _make_engine(_make_agent())
    run_record = RunRecord()

    engine.execute(graph, {}, run_record=run_record)

    assert run_record.status == "failed"


# ---------------------------------------------------------------------------
# Property 7: The run-record store is saved exactly once, and reflects
# failure on exception
# Validates: Requirements 2.5, 2.6
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(message=st.text(max_size=50))
def test_execute_exception_path_saves_once_and_reraises(message: str):
    """Feature: core-orchestration-test-coverage, Property 7: The run-record
    store is saved exactly once, and reflects failure on exception.

    **Validates: Requirements 2.5, 2.6**
    """
    exc = RuntimeError(message)
    graph = MagicMock()
    graph.invoke.side_effect = exc
    store = MagicMock()
    engine = _make_engine(_make_agent(), run_record_store=store)
    run_record = RunRecord()

    with pytest.raises(RuntimeError) as exc_info:
        engine.execute(graph, {}, run_record=run_record)

    assert exc_info.value is exc
    assert run_record.status == "failed"
    assert run_record.errors[-1]["description"] == str(exc)
    store.save.assert_called_once_with(run_record)


@settings(max_examples=100)
@given(entries=test_result_strategy)
def test_execute_success_path_saves_store_exactly_once(entries: list[tuple[str, bool]]):
    """Feature: core-orchestration-test-coverage, Property 7 (success path):
    The run-record store is saved exactly once on normal completion.

    **Validates: Requirements 2.5, 2.6**
    """
    evidence = _build_evidence(entries)
    graph = MagicMock()
    graph.invoke.return_value = {"evidence": evidence}
    store = MagicMock()
    engine = _make_engine(_make_agent(), run_record_store=store)
    run_record = RunRecord()

    engine.execute(graph, {}, run_record=run_record)

    store.save.assert_called_once_with(run_record)


# ---------------------------------------------------------------------------
# Property 8: Omitting the RunRecord skips all run-record store interaction
# Validates: Requirements 2.7
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(entries=test_result_strategy)
def test_execute_without_run_record_skips_store(entries: list[tuple[str, bool]]):
    """Feature: core-orchestration-test-coverage, Property 8: Omitting the
    RunRecord skips all run-record store interaction.

    **Validates: Requirements 2.7**
    """
    evidence = _build_evidence(entries)
    expected_result = {"evidence": evidence}
    graph = MagicMock()
    graph.invoke.return_value = expected_result
    store = MagicMock()
    engine = _make_engine(_make_agent(), run_record_store=store)

    result = engine.execute(graph, {})

    assert result == expected_result
    store.save.assert_not_called()


# ---------------------------------------------------------------------------
# Property 9: Modified files pass through unchanged into the RunRecord
# Validates: Requirements 2.8
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(modified_files=st.lists(st.text(min_size=1, max_size=30), min_size=0, max_size=10))
def test_modified_files_pass_through_unchanged(modified_files: list[str]):
    """Feature: core-orchestration-test-coverage, Property 9: Modified files
    pass through unchanged into the RunRecord.

    **Validates: Requirements 2.8**
    """
    graph = MagicMock()
    graph.invoke.return_value = {"modified_files": modified_files}
    engine = _make_engine(_make_agent())
    run_record = RunRecord()

    engine.execute(graph, {}, run_record=run_record)

    assert run_record.modified_files == modified_files
