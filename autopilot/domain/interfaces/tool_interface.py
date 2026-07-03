"""Tool interface protocol and ToolResult dataclass for the domain layer."""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolResult:
    """Structured result from tool execution."""

    success: bool
    data: Any | None = None
    error: str | None = None


@runtime_checkable
class ToolInterface(Protocol):
    """Protocol that all tools must implement."""

    @property
    def name(self) -> str:
        """Unique string identifier for tool lookup."""
        ...

    @property
    def input_schema(self) -> dict[str, type]:
        """Expected input parameters."""
        ...

    @property
    def output_schema(self) -> dict[str, type]:
        """Expected output structure on success."""
        ...

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool operation.

        Returns:
            ToolResult with success/failure status and data or error description.
        """
        ...
