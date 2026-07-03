"""Property 5: Tool registry lookup failure.

Validates: Requirements 4.6

For any tool name that is not registered in the Tool_Registry, requesting that
name SHALL raise an error that includes the unregistered tool name in the message.
"""

from typing import Any

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from autopilot.application.registries.tool_registry import ToolRegistry
from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult


# ---------------------------------------------------------------------------
# Fake tool implementation for testing
# ---------------------------------------------------------------------------


class FakeTool:
    """A minimal tool implementation satisfying the ToolInterface protocol."""

    def __init__(self, tool_name: str) -> None:
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_schema(self) -> dict[str, type]:
        return {"input": str}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"output": str}

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, data="fake result")


# Verify FakeTool satisfies the protocol at import time
assert isinstance(FakeTool("check"), ToolInterface)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate non-empty tool names (printable strings, min 1 char)
tool_name_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
)


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    registered_names=st.lists(tool_name_strategy, min_size=0, max_size=5, unique=True),
    lookup_name=tool_name_strategy,
)
def test_unregistered_tool_lookup_raises_key_error(
    registered_names: list[str], lookup_name: str
):
    """**Validates: Requirements 4.6**

    Property 5: For any tool name that is not registered in the Tool_Registry,
    requesting that name raises KeyError.
    """
    # Ensure the lookup name is NOT in the registered set
    assume(lookup_name not in registered_names)

    registry = ToolRegistry()
    for name in registered_names:
        registry.register(FakeTool(name))

    with pytest.raises(KeyError):
        registry.get(lookup_name)


@settings(max_examples=100)
@given(
    registered_names=st.lists(tool_name_strategy, min_size=0, max_size=5, unique=True),
    lookup_name=tool_name_strategy,
)
def test_unregistered_tool_error_message_includes_tool_name(
    registered_names: list[str], lookup_name: str
):
    """**Validates: Requirements 4.6**

    Property 5: The KeyError message includes the unregistered tool name,
    so the developer knows which tool was not found.
    """
    # Ensure the lookup name is NOT in the registered set
    assume(lookup_name not in registered_names)

    registry = ToolRegistry()
    for name in registered_names:
        registry.register(FakeTool(name))

    with pytest.raises(KeyError) as exc_info:
        registry.get(lookup_name)

    # The error message (the first arg of the KeyError) must
    # contain the unregistered tool name
    error_message = exc_info.value.args[0]
    assert lookup_name in error_message, (
        f"KeyError message '{error_message}' does not include "
        f"the unregistered tool name '{lookup_name}'"
    )
