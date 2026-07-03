"""Tests for FilesystemTool implementation."""

import os
import tempfile

import pytest

from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult
from autopilot.infrastructure.tools.filesystem_tool import FilesystemTool


@pytest.fixture
def tool():
    """Create a FilesystemTool instance."""
    return FilesystemTool()


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestFilesystemToolProtocol:
    """Test that FilesystemTool implements ToolInterface correctly."""

    def test_implements_tool_interface(self, tool):
        assert isinstance(tool, ToolInterface)

    def test_name_is_filesystem(self, tool):
        assert tool.name == "filesystem"

    def test_input_schema(self, tool):
        assert tool.input_schema == {"operation": str, "path": str, "content": str}

    def test_output_schema(self, tool):
        assert tool.output_schema == {"result": str}


class TestReadOperation:
    """Test the read operation."""

    def test_read_existing_file(self, tool, tmp_dir):
        filepath = os.path.join(tmp_dir, "test.txt")
        with open(filepath, "w") as f:
            f.write("hello world")

        result = tool.execute(operation="read", path=filepath)

        assert result.success is True
        assert result.data == "hello world"
        assert result.error is None

    def test_read_empty_file(self, tool, tmp_dir):
        filepath = os.path.join(tmp_dir, "empty.txt")
        with open(filepath, "w") as f:
            f.write("")

        result = tool.execute(operation="read", path=filepath)

        assert result.success is True
        assert result.data == ""

    def test_read_nonexistent_file(self, tool):
        result = tool.execute(operation="read", path="/nonexistent/path/file.txt")

        assert result.success is False
        assert result.error is not None
        assert "No such file or directory" in result.error

    def test_read_directory_returns_error(self, tool, tmp_dir):
        result = tool.execute(operation="read", path=tmp_dir)

        assert result.success is False
        assert result.error is not None


class TestWriteOperation:
    """Test the write operation."""

    def test_write_new_file(self, tool, tmp_dir):
        filepath = os.path.join(tmp_dir, "new.txt")

        result = tool.execute(operation="write", path=filepath, content="new content")

        assert result.success is True
        assert result.data == "written"
        with open(filepath, "r") as f:
            assert f.read() == "new content"

    def test_write_overwrites_existing(self, tool, tmp_dir):
        filepath = os.path.join(tmp_dir, "existing.txt")
        with open(filepath, "w") as f:
            f.write("old content")

        result = tool.execute(operation="write", path=filepath, content="new content")

        assert result.success is True
        with open(filepath, "r") as f:
            assert f.read() == "new content"

    def test_write_creates_parent_directories(self, tool, tmp_dir):
        filepath = os.path.join(tmp_dir, "nested", "dir", "file.txt")

        result = tool.execute(operation="write", path=filepath, content="nested")

        assert result.success is True
        assert os.path.exists(filepath)
        with open(filepath, "r") as f:
            assert f.read() == "nested"

    def test_write_empty_content(self, tool, tmp_dir):
        filepath = os.path.join(tmp_dir, "empty.txt")

        result = tool.execute(operation="write", path=filepath, content="")

        assert result.success is True
        with open(filepath, "r") as f:
            assert f.read() == ""


class TestListOperation:
    """Test the list operation."""

    def test_list_directory(self, tool, tmp_dir):
        # Create some files
        for name in ["a.txt", "b.txt", "c.txt"]:
            with open(os.path.join(tmp_dir, name), "w") as f:
                f.write("")

        result = tool.execute(operation="list", path=tmp_dir)

        assert result.success is True
        assert sorted(result.data) == ["a.txt", "b.txt", "c.txt"]

    def test_list_empty_directory(self, tool, tmp_dir):
        result = tool.execute(operation="list", path=tmp_dir)

        assert result.success is True
        assert result.data == []

    def test_list_nonexistent_directory(self, tool):
        result = tool.execute(operation="list", path="/nonexistent/directory")

        assert result.success is False
        assert result.error is not None

    def test_list_file_returns_error(self, tool, tmp_dir):
        filepath = os.path.join(tmp_dir, "file.txt")
        with open(filepath, "w") as f:
            f.write("")

        result = tool.execute(operation="list", path=filepath)

        assert result.success is False
        assert result.error is not None


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_missing_operation(self, tool):
        result = tool.execute(path="/some/path")

        assert result.success is False
        assert "Missing required parameter: operation" in result.error

    def test_missing_path(self, tool):
        result = tool.execute(operation="read")

        assert result.success is False
        assert "Missing required parameter: path" in result.error

    def test_unsupported_operation(self, tool):
        result = tool.execute(operation="delete", path="/some/path")

        assert result.success is False
        assert "Unsupported operation: delete" in result.error

    def test_returns_tool_result_type(self, tool, tmp_dir):
        filepath = os.path.join(tmp_dir, "test.txt")
        with open(filepath, "w") as f:
            f.write("data")

        result = tool.execute(operation="read", path=filepath)

        assert isinstance(result, ToolResult)


class TestExportFromInit:
    """Test that FilesystemTool is properly exported."""

    def test_importable_from_package(self):
        from autopilot.infrastructure.tools import FilesystemTool as FT

        assert FT is FilesystemTool
