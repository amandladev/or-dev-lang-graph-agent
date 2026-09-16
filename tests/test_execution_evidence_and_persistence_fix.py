"""Tests for execution-evidence-and-persistence-fix.

Covers:
1. Code_Executor now returns its per-step execution log as evidence.
2. OrchestrationEngine._serialize_state logs persistence failures instead
   of silently swallowing them.
3. Publisher._update_jira applies configured Jira transitions and reports failures.
4. Publisher._load_rules no longer has the redundant (KeyError, Exception)
   except clause.
"""

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.application.orchestrator.retry_policy import RetryPolicy
from autopilot.domain.interfaces.tool_interface import ToolResult
from autopilot.infrastructure.agents.code_executor import CodeExecutorAgent
from autopilot.infrastructure.agents.publisher import PublisherAgent
from autopilot.infrastructure.agents.reviewer import ReviewerAgent

# Code_Executor: execution log returned as evidence


def _make_opencode_registry(results: list) -> MagicMock:
    """Build a fake tool registry whose opencode tool returns `results`
    in order on successive calls to execute()."""
    opencode = MagicMock()
    opencode.execute.side_effect = results
    registry = MagicMock()
    registry.get.return_value = opencode
    return registry


def test_code_executor_returns_evidence_for_successful_steps():
    plan = {
        "ticket_id": "T-1",
        "steps": [
            {"step": 1, "description": "Do thing one"},
            {"step": 2, "description": "Do thing two"},
        ],
    }
    results = [
        MagicMock(success=True, data={"result": "Modified: a.py"}),
        MagicMock(success=True, data={"result": "Modified: b.py"}),
    ]
    registry = _make_opencode_registry(results)
    agent = CodeExecutorAgent(tool_registry=registry)

    output = agent.execute({"plan": plan, "context": {}})

    assert "evidence" in output
    assert len(output["evidence"]) == 1
    evidence_item = output["evidence"][0]
    assert evidence_item["type"] == "execution_log"
    steps = evidence_item["data"]["steps"]
    assert len(steps) == 2
    assert steps[0]["step"] == 1
    assert steps[0]["success"] is True
    assert steps[1]["step"] == 2
    assert steps[1]["success"] is True


def test_code_executor_evidence_records_failed_step():
    plan = {
        "ticket_id": "T-1",
        "steps": [
            {"step": 1, "description": "Do thing one"},
            {"step": 2, "description": "Do thing that fails"},
        ],
    }
    results = [
        MagicMock(success=True, data={"result": "Modified: a.py"}),
        MagicMock(success=False, data=None, error="boom"),
    ]
    registry = _make_opencode_registry(results)
    agent = CodeExecutorAgent(tool_registry=registry)

    output = agent.execute({"plan": plan, "context": {}})

    steps = output["evidence"][0]["data"]["steps"]
    assert steps[1]["step"] == 2
    assert steps[1]["success"] is False
    assert steps[1]["error"] == "boom"


def test_code_executor_no_steps_returns_no_evidence():
    agent = CodeExecutorAgent(tool_registry=MagicMock())
    output = agent.execute({"plan": {"steps": []}, "context": {}})
    assert output == {"modified_files": []}
    assert "evidence" not in output


# Engine: _serialize_state logs persistence failures instead of swallowing


class _FakeRegistry:
    pass


class _FailingSerializer:
    def persist(self, state, filepath):
        raise OSError("disk full")


class _FakeConfig:
    workspace_location = "/tmp"


def _create_engine(logger):
    retry_policy = RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
    return OrchestrationEngine(
        agent_registry=_FakeRegistry(),
        serializer=_FailingSerializer(),
        logger=logger,
        retry_policy=retry_policy,
        config=_FakeConfig(),
    )


def test_serialize_state_logs_warning_on_persistence_failure():
    logger = MagicMock()
    engine = _create_engine(logger)

    # Should not raise despite the serializer failing.
    engine._serialize_state({"ticket": {}, "context": {}})

    logger.log_warning.assert_called_once()
    (message,), _ = logger.log_warning.call_args
    assert "disk full" in message


def test_serialize_state_does_not_crash_workflow_on_failure():
    logger = MagicMock()
    engine = _create_engine(logger)

    try:
        engine._serialize_state({"ticket": {}, "context": {}})
    except Exception as exc:  # pragma: no cover - explicit failure path
        raise AssertionError(
            f"_serialize_state should not raise, but raised: {exc}"
        )


def test_update_jira_applies_target_transition():
    jira = MagicMock()
    jira.execute.return_value = ToolResult(
        success=True,
        data={"applied": "Code Review", "id": "31"},
    )
    registry = MagicMock()
    registry.get.return_value = jira
    agent = PublisherAgent(tool_registry=registry)
    rules = {"jira_transition": "In Progress -> Code Review"}

    result = agent._update_jira("TICKET-1", {"project": "TEST"}, [], rules)

    jira.execute.assert_called_once_with(
        action="apply_transition",
        ticket_id="TICKET-1",
        transition_name="Code Review",
        instance="TEST",
    )
    assert result == {
        "skipped": False,
        "success": True,
        "ticket_id": "TICKET-1",
        "transition": "Code Review",
        "result": {"applied": "Code Review", "id": "31"},
    }


def test_update_jira_reports_transition_failure():
    jira = MagicMock()
    jira.execute.return_value = ToolResult(success=False, error="Transition not available")
    registry = MagicMock()
    registry.get.return_value = jira
    agent = PublisherAgent(tool_registry=registry)

    result = agent._update_jira(
        "TEST-1",
        {},
        [],
        {"jira_transition": "Code Review"},
    )

    assert result["skipped"] is False
    assert result["success"] is False
    assert result["error"] == "Transition not available"
    jira.execute.assert_called_once_with(
        action="apply_transition",
        ticket_id="TEST-1",
        transition_name="Code Review",
        instance="TEST",
    )


def test_update_jira_no_transition_configured_reports_skipped_true():
    agent = PublisherAgent(tool_registry=MagicMock())
    rules = {"jira_transition": ""}

    result = agent._update_jira("TICKET-1", {}, [], rules)

    assert result["skipped"] is True
    assert "reason" in result


# Publisher: _load_rules falls back to defaults when the tool raises


def test_load_rules_falls_back_to_defaults_on_tool_failure():
    registry = MagicMock()
    registry.get.side_effect = KeyError("obsidian")
    agent = PublisherAgent(tool_registry=registry)

    rules = agent._load_rules()

    assert rules["source"] == "default"


def test_load_rules_falls_back_to_defaults_on_generic_exception():
    obsidian = MagicMock()
    obsidian.execute.side_effect = RuntimeError("network error")
    registry = MagicMock()
    registry.get.return_value = obsidian
    agent = PublisherAgent(tool_registry=registry)

    rules = agent._load_rules()

    assert rules["source"] == "default"


# ReviewerAgent: stub-confirmation coverage
# Validates: Requirements 9.1


def test_reviewer_agent_execute_always_raises_not_implemented_error():
    agent = ReviewerAgent(tool_registry=MagicMock())
    with pytest.raises(NotImplementedError):
        agent.execute({"modified_files": [], "context": {}})


@settings(max_examples=100)
@given(
    state=st.dictionaries(
        st.text(max_size=10),
        st.one_of(st.none(), st.text(max_size=10), st.integers()),
        max_size=5,
    )
)
def test_reviewer_agent_execute_raises_not_implemented_for_any_state(state: dict):
    """Feature: core-orchestration-test-coverage, Property 33: ReviewerAgent
    unconditionally raises NotImplementedError.

    **Validates: Requirements 9.1**
    """
    agent = ReviewerAgent(tool_registry=MagicMock())
    with pytest.raises(NotImplementedError):
        agent.execute(state)
