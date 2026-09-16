"""Tests for GraphBuilder: build_work_graph, build_resume_graph, and
_route_after_test.

Covers Requirement 3 of core-orchestration-test-coverage.
"""

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.application.orchestrator.graph_builder import (
    NODE_AGENT_MAP,
    WORK_GRAPH_NODES,
    GraphBuilder,
)


def _passthrough_node_factory(agent_name: str):
    """Return a trivial node callable for any agent name."""

    def _node(state):
        return state

    return _node


def _make_mocked_engine() -> MagicMock:
    engine = MagicMock()
    engine.create_agent_node.side_effect = _passthrough_node_factory
    return engine


def _edge_targets(rendered_graph, source: str, conditional: bool | None = None) -> set[str]:
    """Return the set of target node names reachable from `source`."""
    return {
        e.target
        for e in rendered_graph.edges
        if e.source == source and (conditional is None or e.conditional == conditional)
    }


# 3.1: build_work_graph create_agent_node call counts
# Validates: Requirements 3.1


def test_build_work_graph_calls_create_agent_node_once_per_node():
    engine = _make_mocked_engine()
    builder = GraphBuilder(engine=engine)

    builder.build_work_graph()

    assert engine.create_agent_node.call_count == len(NODE_AGENT_MAP)
    called_names = [c.args[0] for c in engine.create_agent_node.call_args_list]
    assert sorted(called_names) == sorted(NODE_AGENT_MAP.values())


# 3.2: build_work_graph returns compiled graph exposing invoke
# Validates: Requirements 3.2


def test_build_work_graph_returns_compiled_graph_with_invoke():
    engine = _make_mocked_engine()
    builder = GraphBuilder(engine=engine)

    compiled = builder.build_work_graph()

    assert hasattr(compiled, "invoke")
    assert callable(compiled.invoke)


# 3.3/3.4 (part): build_work_graph fixed node/edge topology
# Validates: Requirements 3.3


def test_build_work_graph_has_fixed_topology():
    engine = _make_mocked_engine()
    builder = GraphBuilder(engine=engine)

    compiled = builder.build_work_graph()
    rendered = compiled.get_graph()

    assert _edge_targets(rendered, "context_builder", conditional=False) == {"planner"}
    assert _edge_targets(rendered, "planner", conditional=False) == {"code_executor"}
    assert _edge_targets(rendered, "code_executor", conditional=False) == {"tester"}
    assert _edge_targets(rendered, "publisher", conditional=False) == {"documentation"}
    assert _edge_targets(rendered, "documentation", conditional=False) == {"__end__"}

    tester_conditional_targets = _edge_targets(rendered, "tester", conditional=True)
    assert tester_conditional_targets == {"publisher", "code_executor", "__end__"}


# Property 10: Every graph-builder call wires exactly one node per registered
# agent
# Validates: Requirements 3.1, 3.4


@settings(max_examples=100)
@given(resume_from=st.sampled_from(WORK_GRAPH_NODES))
def test_build_resume_graph_wires_all_nodes_for_valid_resume_points(resume_from: str):
    """Feature: core-orchestration-test-coverage, Property 10: Every
    graph-builder call wires exactly one node per registered agent.

    **Validates: Requirements 3.1, 3.4**
    """
    engine = _make_mocked_engine()
    builder = GraphBuilder(engine=engine)

    builder.build_resume_graph(resume_from=resume_from)

    assert engine.create_agent_node.call_count == len(NODE_AGENT_MAP)
    called_names = [c.args[0] for c in engine.create_agent_node.call_args_list]
    assert sorted(called_names) == sorted(NODE_AGENT_MAP.values())


def test_build_work_graph_call_matches_build_resume_graph_for_named_points():
    """Explicit example check for resume_from == context_builder/tester/documentation.

    **Validates: Requirements 3.4**
    """
    for resume_from in ("context_builder", "tester", "documentation"):
        engine = _make_mocked_engine()
        builder = GraphBuilder(engine=engine)

        builder.build_resume_graph(resume_from=resume_from)

        assert engine.create_agent_node.call_count == len(NODE_AGENT_MAP)


# 3.5 (example): build_resume_graph(resume_from="tester") branching
# Validates: Requirements 3.5


def test_build_resume_graph_tester_has_same_conditional_branching_as_work_graph():
    engine = _make_mocked_engine()
    builder = GraphBuilder(engine=engine)

    compiled = builder.build_resume_graph(resume_from="tester")
    rendered = compiled.get_graph()

    tester_conditional_targets = _edge_targets(rendered, "tester", conditional=True)
    assert tester_conditional_targets == {"publisher", "code_executor", "__end__"}


# Property 11: An invalid resume node is rejected without touching the engine
# Validates: Requirements 3.6


@settings(max_examples=100)
@given(
    resume_from=st.text(min_size=1, max_size=20).filter(
        lambda s: s not in WORK_GRAPH_NODES
    )
)
def test_build_resume_graph_invalid_node_raises_without_touching_engine(resume_from: str):
    """Feature: core-orchestration-test-coverage, Property 11: An invalid
    resume node is rejected without touching the engine.

    **Validates: Requirements 3.6**
    """
    engine = _make_mocked_engine()
    builder = GraphBuilder(engine=engine)

    with pytest.raises(ValueError):
        builder.build_resume_graph(resume_from=resume_from)

    engine.create_agent_node.assert_not_called()


# Property 12: Post-test routing is a total function of the last error's type
# Validates: Requirements 3.7, 3.8, 3.9, 3.10, 3.11


error_type_strategy = st.one_of(
    st.just("retryable"),
    st.just("non_retryable"),
    st.text(min_size=1, max_size=15),
    st.none(),
)


def _error_entry(error_type):
    entry = {"description": "boom"}
    if error_type is not None:
        entry["error_type"] = error_type
    return entry


def test_route_after_test_passed_status_returns_pass():
    """**Validates: Requirements 3.7**"""
    builder = GraphBuilder(engine=MagicMock())
    assert builder._route_after_test({"metadata": {"test_status": "passed"}}) == "pass"


@pytest.mark.parametrize(
    ("status", "attempts", "max_retries", "expected"),
    [
        ("failed", 1, 1, "retry"),
        ("failed", 2, 1, "pause"),
        ("skipped", 1, 3, "pause"),
        (None, 0, 3, "pause"),
    ],
)
def test_route_after_test_enforces_status_and_retry_budget(
    status, attempts, max_retries, expected
):
    engine = MagicMock()
    engine.max_retries = max_retries
    builder = GraphBuilder(engine=engine)

    result = builder._route_after_test({
        "metadata": {"test_status": status, "test_attempts": attempts}
    })

    assert result == expected
