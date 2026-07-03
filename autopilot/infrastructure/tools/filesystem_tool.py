"""Filesystem tool implementation for file read/write/list operations."""

import os
from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult


class FilesystemTool:
    """Tool for basic filesystem operations (read, write, list).

    Implements the ToolInterface protocol for uniform tool access.
    """

    @property
    def name(self) -> str:
        """Unique string identifier for tool lookup."""
        return "filesystem"

    @property
    def input_schema(self) -> dict[str, type]:
        """Expected input parameters."""
        return {"operation": str, "path": str, "content": str}

    @property
    def output_schema(self) -> dict[str, type]:
        """Expected output structure on success."""
        return {"result": str}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a filesystem operation.

        Supported operations:
            - "read": Read file content at the given path.
            - "write": Write content to the file at the given path.
            - "list": List directory contents at the given path.

        Args:
            operation: The filesystem operation to perform.
            path: The filesystem path to operate on.
            content: Content to write (only used for "write" operation).

        Returns:
            ToolResult with success/failure status and data or error description.
        """
        operation: str = kwargs.get("operation", "")
        path: str = kwargs.get("path", "")
        content: str = kwargs.get("content", "")

        if not operation:
            return ToolResult(success=False, error="Missing required parameter: operation")

        if not path:
            return ToolResult(success=False, error="Missing required parameter: path")

        try:
            if operation == "read":
                return self._read(path)
            elif operation == "write":
                return self._write(path, content)
            elif operation == "list":
                return self._list(path)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unsupported operation: {operation}. Supported: read, write, list",
                )
        except FileNotFoundError as exc:
            return ToolResult(success=False, error=str(exc))
        except PermissionError as exc:
            return ToolResult(success=False, error=str(exc))
        except IsADirectoryError as exc:
            return ToolResult(success=False, error=str(exc))
        except NotADirectoryError as exc:
            return ToolResult(success=False, error=str(exc))
        except OSError as exc:
            return ToolResult(success=False, error=str(exc))

    def _read(self, path: str) -> ToolResult:
        """Read file content."""
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
        return ToolResult(success=True, data=data)

    def _write(self, path: str, content: str) -> ToolResult:
        """Write content to file."""
        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(success=True, data="written")

    def _list(self, path: str) -> ToolResult:
        """List directory contents."""
        entries = os.listdir(path)
        return ToolResult(success=True, data=entries)
