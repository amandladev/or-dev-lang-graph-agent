"""Property 4: Agent registry uniqueness and non-interference.

Validates: Requirements 2.5, 2.6

For any set of agents with unique names, registering all of them SHALL succeed
with each agent retrievable by name; and for any agent name already registered,
attempting to register a second agent with the same name SHALL raise an error.
Adding a new agent SHALL not alter the metadata of previously registered agents.
"""

from typing import Any, Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.application.registries.agent_registry import AgentRegistry


# ---------------------------------------------------------------------------
# Fake agent implementing AgentInterface protocol for testing
# ---------------------------------------------------------------------------


class FakeAgent:
    """A minimal agent that satisfies the AgentInterface protocol."""

    def __init__(
        self,
        name: str,
        description: str = "A fake agent for testing",
        input_schema: Optional[dict[str, type]] = None,
        output_schema: Optional[dict[str, type]] = None,
    ) -> None:
        self._name = name
        self._description = description
        self._input_schema = input_schema or {"input": str}
        self._output_schema = output_schema or {"output": str}

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, type]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, type]:
        return self._output_schema

    def execute(
        self,
        state: dict[str, Any],
        memory_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return {"output": "fake result"}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate valid agent names: non-empty printable strings
agent_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
)

# Generate lists of unique agent names
unique_agent_names_strategy = st.lists(
    agent_name_strategy,
    min_size=1,
    max_size=20,
    unique=True,
)


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(names=unique_agent_names_strategy)
def test_register_unique_agents_all_retrievable(names: list[str]):
    """**Validates: Requirements 2.5, 2.6**

    Property 4: For any set of agents with unique names, registering all of
    them succeeds with each agent retrievable by name.
    """
    registry = AgentRegistry()
    agents = [FakeAgent(name=n) for n in names]

    # Register all agents — should not raise
    for agent in agents:
        registry.register(agent)

    # Each agent should be retrievable by its name
    for agent in agents:
        retrieved = registry.get(agent.name)
        assert retrieved is agent, (
            f"Expected to retrieve agent '{agent.name}' but got a different object"
        )


@settings(max_examples=100)
@given(name=agent_name_strategy)
def test_duplicate_registration_raises_value_error(name: str):
    """**Validates: Requirements 2.5, 2.6**

    Property 4: For any agent name already registered, attempting to register
    a second agent with the same name raises ValueError.
    """
    registry = AgentRegistry()
    first_agent = FakeAgent(name=name)
    duplicate_agent = FakeAgent(name=name, description="duplicate agent")

    registry.register(first_agent)

    with pytest.raises(ValueError):
        registry.register(duplicate_agent)


@settings(max_examples=100)
@given(names=unique_agent_names_strategy)
def test_adding_agent_does_not_alter_existing_metadata(names: list[str]):
    """**Validates: Requirements 2.5, 2.6**

    Property 4: Adding a new agent does not alter the metadata (name,
    description, input_schema, output_schema) of previously registered agents.
    """
    registry = AgentRegistry()

    # Track metadata snapshots after each registration
    registered_metadata: dict[str, dict[str, Any]] = {}

    for name in names:
        agent = FakeAgent(
            name=name,
            description=f"Agent {name}",
            input_schema={"field_" + name: str},
            output_schema={"result_" + name: str},
        )
        registry.register(agent)

        # Snapshot current agent's metadata
        registered_metadata[name] = {
            "name": agent.name,
            "description": agent.description,
            "input_schema": agent.input_schema,
            "output_schema": agent.output_schema,
        }

        # Verify all previously registered agents still have unchanged metadata
        for prev_name, expected_meta in registered_metadata.items():
            retrieved = registry.get(prev_name)
            assert retrieved.name == expected_meta["name"], (
                f"Agent '{prev_name}' name changed after registering '{name}'"
            )
            assert retrieved.description == expected_meta["description"], (
                f"Agent '{prev_name}' description changed after registering '{name}'"
            )
            assert retrieved.input_schema == expected_meta["input_schema"], (
                f"Agent '{prev_name}' input_schema changed after registering '{name}'"
            )
            assert retrieved.output_schema == expected_meta["output_schema"], (
                f"Agent '{prev_name}' output_schema changed after registering '{name}'"
            )
