"""Unit tests for ResumeCommand use case.

Validates: Requirements 1.3, 13.4

WHEN the user executes `autopilot resume`, THE CLI SHALL resume a previously
paused or failed workflow from its last successful step by deserializing
the persisted Workflow_State.
"""

from unittest.mock import MagicMock, patch
import uuid

from autopilot.application.use_cases.resume_command import ResumeCommand
from autopilot.domain.entities.config import Config
from autopilot.domain.entities.workflow_state import WorkflowState


def _make_config(workspace: str = "/tmp/workspace") -> Config:
    """Create a test Config instance."""
    return Config(vault_location="/tmp/vault", workspace_location=workspace)


def _make_mock_serializer(state: WorkflowState | None = None):
    """Create a mock serializer that returns the given state on load."""
    serializer = MagicMock()
    if state is None:
        state = WorkflowState()
    serializer.load.return_value = state
    return serializer


def _make_mock_engine():
    """Create a mock orchestration engine."""
    engine = MagicMock()
    engine.execute.return_value = {}
    return engine


def _make_mock_graph_builder():
    """Create a mock graph builder."""
    builder = MagicMock()
    builder.build_resume_graph.return_value = MagicMock()
    return builder


def test_resume_command_loads_state_from_correct_path():
    """ResumeCommand loads state from workspace_location/.autopilot_state.json."""
    config = _make_config(workspace="/home/user/project")
    serializer = _make_mock_serializer()
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    cmd.execute()

    serializer.load.assert_called_once_with("/home/user/project/.autopilot_state.json")


def test_resume_command_returns_uuid_string():
    """ResumeCommand.execute() returns a valid UUID string."""
    config = _make_config()
    serializer = _make_mock_serializer()
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    result = cmd.execute()

    # Should be a valid UUID
    uuid.UUID(result)  # Raises ValueError if invalid


def test_resume_command_no_logs_resumes_from_context_builder():
    """When no logs exist, resume from the beginning (context_builder)."""
    state = WorkflowState(logs=[])
    config = _make_config()
    serializer = _make_mock_serializer(state)
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    cmd.execute()

    builder.build_resume_graph.assert_called_once_with("context_builder")


def test_resume_command_resumes_after_last_successful_step():
    """When logs show context_builder succeeded, resume from planner."""
    state = WorkflowState(
        logs=[
            {"agent_name": "Context_Builder", "status": "success"},
        ]
    )
    config = _make_config()
    serializer = _make_mock_serializer(state)
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    cmd.execute()

    builder.build_resume_graph.assert_called_once_with("planner")


def test_resume_command_multiple_logs_uses_last_success():
    """When multiple successes exist, resume from node after the last one."""
    state = WorkflowState(
        logs=[
            {"agent_name": "Context_Builder", "status": "success"},
            {"agent_name": "Planner", "status": "success"},
            {"agent_name": "Code_Executor", "status": "success"},
            {"agent_name": "Tester", "status": "failed"},
        ]
    )
    config = _make_config()
    serializer = _make_mock_serializer(state)
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    cmd.execute()

    # Last successful was Code_Executor, so resume from tester
    builder.build_resume_graph.assert_called_once_with("tester")


def test_resume_command_all_failed_resumes_from_beginning():
    """When all logs show failure, resume from context_builder."""
    state = WorkflowState(
        logs=[
            {"agent_name": "Context_Builder", "status": "failed"},
        ]
    )
    config = _make_config()
    serializer = _make_mock_serializer(state)
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    cmd.execute()

    builder.build_resume_graph.assert_called_once_with("context_builder")


def test_resume_command_executes_graph_with_restored_state():
    """ResumeCommand passes the restored state dict to engine.execute()."""
    state = WorkflowState(
        ticket={"id": "TICKET-42"},
        context={"notes": ["some context"]},
        logs=[
            {"agent_name": "Context_Builder", "status": "success"},
        ],
    )
    config = _make_config()
    serializer = _make_mock_serializer(state)
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()
    mock_graph = MagicMock()
    builder.build_resume_graph.return_value = mock_graph

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    cmd.execute()

    # Engine should be called with the built graph and a state dict
    engine.execute.assert_called_once()
    call_args = engine.execute.call_args
    assert call_args[0][0] is mock_graph
    state_dict = call_args[0][1]
    assert state_dict["ticket"] == {"id": "TICKET-42"}
    assert state_dict["context"] == {"notes": ["some context"]}


def test_resume_command_publisher_success_resumes_documentation():
    """When publisher is last success, resume from documentation."""
    state = WorkflowState(
        logs=[
            {"agent_name": "Context_Builder", "status": "success"},
            {"agent_name": "Planner", "status": "success"},
            {"agent_name": "Code_Executor", "status": "success"},
            {"agent_name": "Tester", "status": "success"},
            {"agent_name": "Publisher", "status": "success"},
        ]
    )
    config = _make_config()
    serializer = _make_mock_serializer(state)
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    cmd.execute()

    builder.build_resume_graph.assert_called_once_with("documentation")


def test_resume_command_last_node_success_resumes_from_last():
    """When documentation (last node) is successful, resume from documentation."""
    state = WorkflowState(
        logs=[
            {"agent_name": "Context_Builder", "status": "success"},
            {"agent_name": "Planner", "status": "success"},
            {"agent_name": "Code_Executor", "status": "success"},
            {"agent_name": "Tester", "status": "success"},
            {"agent_name": "Publisher", "status": "success"},
            {"agent_name": "Documentation_Agent", "status": "success"},
        ]
    )
    config = _make_config()
    serializer = _make_mock_serializer(state)
    engine = _make_mock_engine()
    builder = _make_mock_graph_builder()

    cmd = ResumeCommand(engine=engine, graph_builder=builder, serializer=serializer, config=config)
    cmd.execute()

    # Documentation is the last node, should resume from documentation itself
    builder.build_resume_graph.assert_called_once_with("documentation")
