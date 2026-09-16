"""Tests for the human-in-the-loop approval gate."""

from unittest.mock import MagicMock, patch

import pytest

from autopilot.domain.entities.config import Config
from autopilot.infrastructure.adapters.console_approval_gate import ConsoleApprovalGate


def _config(approvals: list[str]) -> Config:
    return Config(
        vault_location="/tmp/vault",
        workspace_location="/tmp/ws",
        approvals=approvals,
    )


def test_approval_not_configured_returns_true():
    gate = ConsoleApprovalGate(config=_config([]))
    assert gate.require("plan", {"plan": {"steps": []}}) is True


def test_approval_configured_prompts_and_accepts():
    gate = ConsoleApprovalGate(config=_config(["plan"]))
    with patch("sys.stdin") as stdin, patch("builtins.input", return_value="y"):
        stdin.isatty.return_value = True
        assert gate.require("plan") is True


def test_approval_configured_rejects_on_no():
    gate = ConsoleApprovalGate(config=_config(["plan"]))
    with patch("sys.stdin") as stdin, patch("builtins.input", return_value="n"):
        stdin.isatty.return_value = True
        assert gate.require("plan") is False


def test_approval_configured_non_tty_auto_approves():
    gate = ConsoleApprovalGate(config=_config(["plan"]))
    with patch("sys.stdin") as stdin:
        stdin.isatty.return_value = False
        assert gate.require("plan") is True


def test_approval_skip_all_bypasses_prompt():
    gate = ConsoleApprovalGate(config=_config(["plan"]))
    gate.skip_all(True)
    with patch("sys.stdin") as stdin, patch("builtins.input") as input_mock:
        stdin.isatty.return_value = True
        assert gate.require("plan") is True
        input_mock.assert_not_called()


def test_approval_renders_plan_details(capsys):
    gate = ConsoleApprovalGate(config=_config([]))
    plan = {"steps": [{"step": 1, "description": "Create src/hello.py"}, {"step": 2, "description": ""}]}
    gate._render_details({"plan": plan})
    captured = capsys.readouterr().out
    assert "Create src/hello.py" in captured
    assert "2." not in captured.replace("1.", "")


def test_config_rejects_unknown_approval_gate():
    with pytest.raises(ValueError, match="approvals"):
        Config(
            vault_location="/tmp/vault",
            workspace_location="/tmp/ws",
            approvals=["publish"],
        )


def test_graph_builder_adds_gate_node_with_approval_gate():

    from autopilot.application.orchestrator.graph_builder import GraphBuilder

    engine = MagicMock()
    engine.create_agent_node.return_value = lambda state: state
    gate = MagicMock()
    gate.require.return_value = True
    builder = GraphBuilder(engine=engine, approval_gate=gate)

    compiled = builder.build_work_graph()
    rendered = compiled.get_graph()

    sources = {e.source for e in rendered.edges}
    assert "plan_approval" in sources

    gate.require.assert_not_called()


def test_graph_builder_gate_node_invokes_approval():

    from autopilot.application.orchestrator.graph_builder import GraphBuilder

    engine = MagicMock()
    engine.create_agent_node.return_value = lambda state: state
    gate = MagicMock()
    gate.require.return_value = True
    builder = GraphBuilder(engine=engine, approval_gate=gate)

    plan_approval_node = builder._make_approval_node("plan")

    state = {"plan": {"steps": [{"step": 1, "description": "x"}]}}
    plan_approval_node(state)
    gate.require.assert_called_once_with("plan", {"plan": state["plan"]})


def test_graph_builder_gate_node_raises_on_rejection():

    from autopilot.application.orchestrator.graph_builder import GraphBuilder
    from autopilot.domain.value_objects.exceptions import ApprovalRejectedError

    engine = MagicMock()
    gate = MagicMock()
    gate.require.return_value = False
    builder = GraphBuilder(engine=engine, approval_gate=gate)

    node = builder._make_approval_node("plan")
    with pytest.raises(ApprovalRejectedError):
        node({"plan": {}})


def test_engine_marks_run_cancelled_on_approval_rejection():

    import pytest

    from autopilot.application.orchestrator.engine import OrchestrationEngine
    from autopilot.domain.entities.config import Config
    from autopilot.domain.entities.run_record import RunRecord
    from autopilot.domain.value_objects.exceptions import ApprovalRejectedError

    config = Config(vault_location="/tmp/v", workspace_location="/tmp/w")
    engine = OrchestrationEngine(
        agent_registry=MagicMock(),
        serializer=MagicMock(),
        logger=MagicMock(),
        retry_policy=MagicMock(),
        config=config,
    )

    graph = MagicMock()
    graph.invoke.side_effect = ApprovalRejectedError("plan rejected")

    run_record = RunRecord(ticket_id="T-1")
    with pytest.raises(ApprovalRejectedError):
        engine.execute(graph, {}, run_record=run_record)

    assert run_record.status == "cancelled"