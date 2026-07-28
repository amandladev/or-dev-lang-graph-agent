"""Tests for PlannerAgent with mocked OpenCode tool and knowledge engine.

Covers Requirement 6 of core-orchestration-test-coverage.
"""

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.domain.entities.experience import Experience
from autopilot.domain.interfaces.tool_interface import ToolResult
from autopilot.infrastructure.agents.planner import PlannerAgent

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

single_line_text_strategy = st.text(
    alphabet=st.characters(blacklist_characters="\n\r"),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")

no_digit_period_text_strategy = st.text(
    alphabet=st.characters(blacklist_categories=("Nd",), blacklist_characters="\n\r."),
    min_size=1,
    max_size=60,
).filter(lambda s: s.strip() != "")


def _make_tool_registry_with_opencode(tool_result: ToolResult) -> MagicMock:
    opencode = MagicMock()
    opencode.execute.return_value = tool_result
    registry = MagicMock()
    registry.get.return_value = opencode
    return registry, opencode


# ---------------------------------------------------------------------------
# Property 19: Numbered-line OpenCode responses parse into one step per line
# Validates: Requirements 6.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(descriptions=st.lists(single_line_text_strategy, min_size=1, max_size=8))
def test_numbered_line_response_parses_one_step_per_line(descriptions: list[str]):
    """Feature: core-orchestration-test-coverage, Property 19:
    Numbered-line OpenCode responses parse into one step per line.

    **Validates: Requirements 6.1**
    """
    response_text = "\n".join(
        f"{i + 1}. {desc}" for i, desc in enumerate(descriptions)
    )
    registry, opencode = _make_tool_registry_with_opencode(
        ToolResult(success=True, data={"result": response_text})
    )
    agent = PlannerAgent(tool_registry=registry)

    output = agent.execute({"ticket": {"id": "T-1"}, "context": {}})

    steps = output["plan"]["steps"]
    assert len(steps) == len(descriptions)
    for step in steps:
        assert step["agent"] == "Code_Executor"
        assert "step" in step
        assert "description" in step


# ---------------------------------------------------------------------------
# Property 20: Responses with no numbered lines collapse to a single
# whole-text step
# Validates: Requirements 6.6
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(response_text=no_digit_period_text_strategy)
def test_no_numbered_lines_collapses_to_single_step(response_text: str):
    """Feature: core-orchestration-test-coverage, Property 20: Responses
    with no numbered lines collapse to a single whole-text step.

    **Validates: Requirements 6.6**
    """
    registry, opencode = _make_tool_registry_with_opencode(
        ToolResult(success=True, data={"result": response_text})
    )
    agent = PlannerAgent(tool_registry=registry)

    output = agent.execute({"ticket": {"id": "T-1"}, "context": {}})

    steps = output["plan"]["steps"]
    assert len(steps) == 1
    assert steps[0]["description"] == response_text.strip()


# ---------------------------------------------------------------------------
# Property 21: Missing or failing OpenCode tool always yields a single-step
# fallback plan
# Validates: Requirements 6.2, 6.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(title=st.text(min_size=0, max_size=50))
def test_missing_opencode_tool_yields_single_step_fallback_without_reason(title: str):
    """Feature: core-orchestration-test-coverage, Property 21 (missing tool
    branch): Missing OpenCode tool always yields a single-step fallback plan
    with no fallback_reason.

    **Validates: Requirements 6.2**
    """
    registry = MagicMock()
    registry.get.side_effect = KeyError("opencode")
    agent = PlannerAgent(tool_registry=registry)

    output = agent.execute({"ticket": {"id": "T-1", "title": title}, "context": {}})

    plan = output["plan"]
    assert len(plan["steps"]) == 1
    assert "fallback_reason" not in plan


@settings(max_examples=100)
@given(error_message=st.text(min_size=1, max_size=50))
def test_failing_opencode_tool_yields_single_step_fallback_with_reason(error_message: str):
    """Feature: core-orchestration-test-coverage, Property 21 (failing tool
    branch): Failing OpenCode tool always yields a single-step fallback plan
    whose fallback_reason equals the tool's error.

    **Validates: Requirements 6.3**
    """
    registry, opencode = _make_tool_registry_with_opencode(
        ToolResult(success=False, data=None, error=error_message)
    )
    agent = PlannerAgent(tool_registry=registry)

    output = agent.execute({"ticket": {"id": "T-1"}, "context": {}})

    plan = output["plan"]
    assert len(plan["steps"]) == 1
    assert plan["fallback_reason"] == error_message


# ---------------------------------------------------------------------------
# Property 22: The prompt mentions past experiences iff the knowledge engine
# found any
# Validates: Requirements 6.4, 6.7
# ---------------------------------------------------------------------------


def _make_experience(index: int) -> Experience:
    return Experience(
        id=f"exp-{index}",
        ticket_id=f"TICKET-{index}",
        objective=f"Objective {index}",
        solution_description=f"Solution {index}",
    )


@settings(max_examples=100)
@given(num_experiences=st.integers(min_value=0, max_value=5))
def test_prompt_mentions_past_experiences_iff_found(num_experiences: int):
    """Feature: core-orchestration-test-coverage, Property 22: The prompt
    mentions past experiences if and only if the knowledge engine found any.

    **Validates: Requirements 6.4, 6.7**
    """
    experiences = [_make_experience(i) for i in range(num_experiences)]
    registry, opencode = _make_tool_registry_with_opencode(
        ToolResult(success=True, data={"result": "1. Do it"})
    )
    knowledge_engine = MagicMock()
    knowledge_engine.find_similar.return_value = experiences
    agent = PlannerAgent(tool_registry=registry, knowledge_engine=knowledge_engine)

    agent.execute({"ticket": {"id": "T-1"}, "context": {}})

    prompt = opencode.execute.call_args.kwargs["prompt"]
    if num_experiences > 0:
        assert "PAST EXPERIENCES" in prompt
    else:
        assert "PAST EXPERIENCES" not in prompt


# ---------------------------------------------------------------------------
# Property 23: Knowledge-engine failures never prevent plan generation
# Validates: Requirements 6.5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(error_message=st.text(min_size=0, max_size=50))
def test_knowledge_engine_failure_never_blocks_plan_generation(error_message: str):
    """Feature: core-orchestration-test-coverage, Property 23:
    Knowledge-engine failures never prevent plan generation.

    **Validates: Requirements 6.5**
    """
    registry, opencode = _make_tool_registry_with_opencode(
        ToolResult(success=True, data={"result": "1. Do it"})
    )
    knowledge_engine = MagicMock()
    knowledge_engine.find_similar.side_effect = RuntimeError(error_message)
    agent = PlannerAgent(tool_registry=registry, knowledge_engine=knowledge_engine)

    output = agent.execute({"ticket": {"id": "T-1"}, "context": {}})

    opencode.execute.assert_called_once()
    assert "plan" in output
