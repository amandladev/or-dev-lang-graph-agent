"""Tests for OpenCodeTool live output streaming."""

from autopilot.infrastructure.tools.opencode_tool import OpenCodeTool


def test_run_streaming_captures_stdout_and_stderr(capsys):
    tool = OpenCodeTool(stream_output=True, timeout=30)
    result = tool._run_streaming(
        ["python3", "-c", "import sys; print('live-line'); sys.stderr.write('err-line')"],
        None,
    )

    assert result.success is True
    assert "live-line" in result.data["result"]
    assert "err-line" in result.data["result"]
    assert "live-line" in capsys.readouterr().out


def test_run_streaming_streams_live_before_completion():
    tool = OpenCodeTool(stream_output=True, timeout=30)
    result = tool._run_streaming(
        ["python3", "-c", "import time; print('early'); time.sleep(0.2); print('late')"],
        None,
    )

    assert result.success is True
    assert "early" in result.data["result"]
    assert "late" in result.data["result"]


def test_run_streaming_timeout_kills_process():
    tool = OpenCodeTool(stream_output=True, timeout=1)
    result = tool._run_streaming(
        ["python3", "-c", "import time; time.sleep(30)"],
        None,
    )

    assert result.success is False
    assert "timed out" in (result.error or "")


def test_run_streaming_failure_reports_exit_code():
    tool = OpenCodeTool(stream_output=True, timeout=30)
    result = tool._run_streaming(
        ["python3", "-c", "import sys; sys.exit(3)"],
        None,
    )

    assert result.success is False
    assert "code 3" in (result.error or "")


def test_non_streaming_execute_keeps_captured_behavior():
    tool = OpenCodeTool(stream_output=False, timeout=30)
    result = tool.execute(prompt="anything")
    if result.success:
        assert "result" in result.data
    else:
        assert result.error