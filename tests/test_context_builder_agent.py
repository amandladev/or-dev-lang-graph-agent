"""Tests for ContextBuilderAgent with mocked Jira and Obsidian tools.

Covers Requirement 7 of core-orchestration-test-coverage.
"""

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.domain.interfaces.tool_interface import ToolResult
from autopilot.infrastructure.agents.context_builder import ContextBuilderAgent


def _make_registry(jira=None, obsidian=None, missing: set[str] = frozenset()) -> MagicMock:
    tools = {}
    if jira is not None:
        tools["jira"] = jira
    if obsidian is not None:
        tools["obsidian"] = obsidian

    def _get(name):
        if name in missing:
            raise KeyError(name)
        if name in tools:
            return tools[name]
        raise KeyError(name)

    registry = MagicMock()
    registry.get.side_effect = _get
    return registry


# ---------------------------------------------------------------------------
# Property 24: A missing or empty ticket ID short-circuits context building
# without contacting Jira
# Validates: Requirements 7.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    ticket=st.one_of(
        st.just({}),
        st.fixed_dictionaries({"id": st.just("")}),
        st.dictionaries(st.text(min_size=1, max_size=10), st.text(max_size=10)).map(
            lambda d: {**d, "id": ""}
        ),
    )
)
def test_missing_or_empty_id_short_circuits_without_jira_call(ticket: dict):
    """Feature: core-orchestration-test-coverage, Property 24: A missing or
    empty ticket ID short-circuits context building without contacting Jira.

    **Validates: Requirements 7.1**
    """
    jira = MagicMock()
    registry = _make_registry(jira=jira)
    agent = ContextBuilderAgent(tool_registry=registry)

    output = agent.execute({"ticket": ticket})

    assert output["ticket"] == ticket
    assert "error" in output["context"]
    assert output["context"]["sources"] == []
    jira.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Property 25: Jira tool outcomes propagate faithfully into
# _fetch_ticket's return value
# Validates: Requirements 7.2, 7.3, 7.6
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    ticket_data=st.fixed_dictionaries(
        {
            "id": st.text(min_size=1, max_size=10),
            "title": st.text(max_size=20),
            "description": st.text(max_size=20),
        }
    )
)
def test_jira_success_propagates_ticket_data_unchanged(ticket_data: dict):
    """Feature: core-orchestration-test-coverage, Property 25 (success
    branch): Jira tool success propagates ticket data unchanged.

    **Validates: Requirements 7.2**
    """
    jira = MagicMock()
    jira.execute.return_value = ToolResult(success=True, data=ticket_data)
    registry = _make_registry(jira=jira)
    agent = ContextBuilderAgent(tool_registry=registry)

    output = agent.execute({"ticket": {"id": ticket_data["id"]}})

    assert output["ticket"] == ticket_data


@settings(max_examples=100)
@given(ticket_id=st.text(min_size=1, max_size=15))
def test_jira_not_registered_returns_dict_with_id_and_error(ticket_id: str):
    """Feature: core-orchestration-test-coverage, Property 25 (not
    registered branch): Missing Jira tool yields a dict with the ticket ID
    and an error key.

    **Validates: Requirements 7.3**
    """
    registry = _make_registry(missing={"jira"})
    agent = ContextBuilderAgent(tool_registry=registry)

    result = agent._fetch_ticket(ticket_id)

    assert result["id"] == ticket_id
    assert "error" in result


@settings(max_examples=100)
@given(
    ticket_id=st.text(min_size=1, max_size=15),
    error_message=st.text(min_size=0, max_size=30),
)
def test_jira_registered_but_failing_returns_dict_with_empty_fields(
    ticket_id: str, error_message: str
):
    """Feature: core-orchestration-test-coverage, Property 25 (failing
    branch): Registered-but-failing Jira tool yields a dict with the ticket
    ID, empty fields, and the tool's error.

    **Validates: Requirements 7.6**
    """
    jira = MagicMock()
    jira.execute.return_value = ToolResult(success=False, data=None, error=error_message)
    registry = _make_registry(jira=jira)
    agent = ContextBuilderAgent(tool_registry=registry)

    result = agent._fetch_ticket(ticket_id)

    assert result["id"] == ticket_id
    assert result["title"] == ""
    assert result["description"] == ""
    assert result["status"] == ""
    assert result["error"] == error_message


# ---------------------------------------------------------------------------
# Property 26: Obsidian notes are reflected in context sources with an
# accurate count
# Validates: Requirements 7.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    notes=st.lists(
        st.fixed_dictionaries({"title": st.text(min_size=1, max_size=15)}),
        min_size=1,
        max_size=8,
    )
)
def test_obsidian_success_with_notes_reflected_with_accurate_count(notes: list[dict]):
    """Feature: core-orchestration-test-coverage, Property 26: Obsidian
    notes are reflected in context sources with an accurate count.

    **Validates: Requirements 7.4**
    """
    jira = MagicMock()
    jira.execute.return_value = ToolResult(
        success=True, data={"id": "T-1", "title": "Fix the widget", "labels": ["bug"]}
    )
    obsidian = MagicMock()
    obsidian.execute.return_value = ToolResult(success=True, data=notes)
    registry = _make_registry(jira=jira, obsidian=obsidian)
    agent = ContextBuilderAgent(tool_registry=registry)

    output = agent.execute({"ticket": {"id": "T-1"}})

    sources = output["context"]["sources"]
    obsidian_sources = [s for s in sources if s.get("type") == "obsidian_notes"]
    assert len(obsidian_sources) == 1
    assert obsidian_sources[0]["count"] == len(notes)


# ---------------------------------------------------------------------------
# Property 27: A failing Obsidian search always yields an empty note list
# Validates: Requirements 7.5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(error_message=st.text(min_size=0, max_size=30))
def test_failing_obsidian_search_yields_empty_note_list(error_message: str):
    """Feature: core-orchestration-test-coverage, Property 27: A failing
    Obsidian search always yields an empty note list.

    **Validates: Requirements 7.5**
    """
    obsidian = MagicMock()
    obsidian.execute.return_value = ToolResult(success=False, data=None, error=error_message)
    registry = _make_registry(obsidian=obsidian)
    agent = ContextBuilderAgent(tool_registry=registry)

    result = agent._search_obsidian("some query")

    assert result == []


# ---------------------------------------------------------------------------
# Property 28: Non-empty description and comments each contribute a
# distinct source entry
# Validates: Requirements 7.7
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    description=st.text(min_size=1, max_size=30),
    comments=st.lists(
        st.fixed_dictionaries({"author": st.text(max_size=10), "body": st.text(max_size=20)}),
        min_size=1,
        max_size=3,
    ),
)
def test_description_and_comments_each_contribute_distinct_source_entry(
    description: str, comments: list[dict]
):
    """Feature: core-orchestration-test-coverage, Property 28: Non-empty
    description and comments each contribute a distinct source entry.

    **Validates: Requirements 7.7**
    """
    jira = MagicMock()
    jira.execute.return_value = ToolResult(
        success=True,
        data={"id": "T-1", "description": description, "comments": comments},
    )
    registry = _make_registry(jira=jira)
    agent = ContextBuilderAgent(tool_registry=registry)

    output = agent.execute({"ticket": {"id": "T-1"}})

    source_types = {s["type"] for s in output["context"]["sources"]}
    assert "jira_description" in source_types
    assert "jira_comments" in source_types


# ---------------------------------------------------------------------------
# Property 29: Absence of title and labels skips the Obsidian search
# entirely
# Validates: Requirements 7.8
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(description=st.text(max_size=20))
def test_no_title_no_labels_skips_obsidian_search(description: str):
    """Feature: core-orchestration-test-coverage, Property 29: Absence of
    title and labels skips the Obsidian search entirely.

    **Validates: Requirements 7.8**
    """
    jira = MagicMock()
    jira.execute.return_value = ToolResult(
        success=True, data={"id": "T-1", "title": "", "labels": [], "description": description}
    )
    obsidian = MagicMock()
    registry = _make_registry(jira=jira, obsidian=obsidian)
    agent = ContextBuilderAgent(tool_registry=registry)

    output = agent.execute({"ticket": {"id": "T-1"}})

    obsidian.execute.assert_not_called()
    assert output["context"]["related_notes"] == []
