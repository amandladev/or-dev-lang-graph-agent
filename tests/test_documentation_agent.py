"""Tests for DocumentationAgent.

Covers Requirement 8 of core-orchestration-test-coverage.
"""

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.agents.documentation import DocumentationAgent

_agent = DocumentationAgent(tool_registry=MagicMock())

description_strategy = st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != "")
file_path_strategy = st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != "")


def _distinct_pair_strategy(strategy):
    return st.tuples(strategy, strategy).filter(lambda pair: pair[0] != pair[1])


# ---------------------------------------------------------------------------
# Property 30: The documentation draft contains every step, file, and
# evidence item supplied
# Validates: Requirements 8.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    step_descriptions=_distinct_pair_strategy(description_strategy),
    file_paths=_distinct_pair_strategy(file_path_strategy),
    evidence_descriptions=_distinct_pair_strategy(description_strategy),
    statuses=st.tuples(
        st.sampled_from(["passed", "failed", "skipped"]),
        st.sampled_from(["passed", "failed", "skipped"]),
    ).filter(lambda pair: pair[0] != pair[1]),
)
def test_draft_contains_every_step_file_and_evidence_item(
    step_descriptions, file_paths, evidence_descriptions, statuses
):
    """Feature: core-orchestration-test-coverage, Property 30: The
    documentation draft contains every step, file, and evidence item
    supplied.

    **Validates: Requirements 8.1**
    """
    plan = {
        "ticket_id": "T-1",
        "steps": [
            {"step": 1, "description": step_descriptions[0]},
            {"step": 2, "description": step_descriptions[1]},
        ],
    }
    modified_files = list(file_paths)
    evidence = [
        {"description": evidence_descriptions[0], "data": {"status": statuses[0]}},
        {"description": evidence_descriptions[1], "data": {"status": statuses[1]}},
    ]

    output = _agent.execute(
        {"plan": plan, "evidence": evidence, "modified_files": modified_files}
    )

    draft = output["metadata"]["documentation_draft"]
    assert step_descriptions[0] in draft
    assert step_descriptions[1] in draft
    for f in file_paths:
        assert f in draft
    for item in evidence:
        assert item["description"] in draft
        assert item["data"]["status"] in draft


# ---------------------------------------------------------------------------
# Property 31: Empty file or evidence lists always produce their respective
# placeholder text
# Validates: Requirements 8.2, 8.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    plan=st.fixed_dictionaries(
        {"ticket_id": st.text(max_size=10), "steps": st.lists(st.fixed_dictionaries(
            {"step": st.integers(min_value=1, max_value=10), "description": description_strategy}
        ), max_size=3)}
    ),
    evidence=st.lists(
        st.fixed_dictionaries(
            {"description": description_strategy, "data": st.fixed_dictionaries(
                {"status": st.sampled_from(["passed", "failed", "skipped"])}
            )}
        ),
        max_size=3,
    ),
)
def test_empty_modified_files_produces_placeholder(plan, evidence):
    """Feature: core-orchestration-test-coverage, Property 31 (files
    branch): Empty modified_files always produces "No files tracked".

    **Validates: Requirements 8.2**
    """
    output = _agent.execute({"plan": plan, "evidence": evidence, "modified_files": []})
    draft = output["metadata"]["documentation_draft"]
    assert "No files tracked" in draft


@settings(max_examples=100)
@given(
    plan=st.fixed_dictionaries(
        {"ticket_id": st.text(max_size=10), "steps": st.lists(st.fixed_dictionaries(
            {"step": st.integers(min_value=1, max_value=10), "description": description_strategy}
        ), max_size=3)}
    ),
    modified_files=st.lists(file_path_strategy, max_size=3),
)
def test_empty_evidence_produces_placeholder(plan, modified_files):
    """Feature: core-orchestration-test-coverage, Property 31 (evidence
    branch): Empty evidence always produces "No test evidence recorded".

    **Validates: Requirements 8.3**
    """
    output = _agent.execute({"plan": plan, "evidence": [], "modified_files": modified_files})
    draft = output["metadata"]["documentation_draft"]
    assert "No test evidence recorded" in draft


# ---------------------------------------------------------------------------
# Property 32: Successful documentation generation always reports status
# "generated"
# Validates: Requirements 8.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    plan=st.fixed_dictionaries(
        {"ticket_id": st.text(max_size=10), "steps": st.lists(st.fixed_dictionaries(
            {"step": st.integers(min_value=1, max_value=10), "description": description_strategy}
        ), max_size=3)}
    ),
    modified_files=st.lists(file_path_strategy, max_size=3),
    evidence=st.lists(
        st.fixed_dictionaries(
            {"description": description_strategy, "data": st.fixed_dictionaries(
                {"status": st.sampled_from(["passed", "failed", "skipped"])}
            )}
        ),
        max_size=3,
    ),
)
def test_successful_generation_reports_status_generated(plan, modified_files, evidence):
    """Feature: core-orchestration-test-coverage, Property 32: Successful
    documentation generation always reports status "generated".

    **Validates: Requirements 8.4**
    """
    output = _agent.execute(
        {"plan": plan, "evidence": evidence, "modified_files": modified_files}
    )
    assert output["metadata"]["documentation_status"] == "generated"
