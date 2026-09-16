"""Tests for TesterAgent test framework detection."""

from autopilot.application.registries.tool_registry import ToolRegistry
from autopilot.infrastructure.agents.tester import TesterAgent


def _make_agent() -> TesterAgent:
    return TesterAgent(ToolRegistry())


def test_detects_pytest_with_pyproject_toml(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    monkeypatch.chdir(tmp_path)
    cfg = _make_agent()._detect_test_config()
    assert cfg == {"framework": "pytest", "command": "python3 -m pytest --tb=short"}


def test_detects_pytest_without_config_file(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_hello.py").write_text("def test_x():\n    pass\n")
    monkeypatch.chdir(tmp_path)
    cfg = _make_agent()._detect_test_config()
    assert cfg == {"framework": "pytest", "command": "python3 -m pytest --tb=short"}


def test_detects_pytest_with_flat_test_file(tmp_path, monkeypatch):
    (tmp_path / "test_hello.py").write_text("def test_x():\n    pass\n")
    monkeypatch.chdir(tmp_path)
    cfg = _make_agent()._detect_test_config()
    assert cfg == {"framework": "pytest", "command": "python3 -m pytest --tb=short"}


def test_no_detection_without_test_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _make_agent()._detect_test_config() is None


def test_skip_evidence_when_no_framework(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = _make_agent().execute({"modified_files": ["src/a.py"]})
    assert output["evidence"][0]["data"]["status"] == "skipped"