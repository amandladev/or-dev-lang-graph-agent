"""Tests for ObsidianTool vault search behavior."""

import pytest

from autopilot.infrastructure.tools.obsidian_tool import ObsidianTool


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "note.md").write_text("feature implementation notes for DFX5", encoding="utf-8")
    (tmp_path / ".autopilot-rules.md").write_text(
        "- branch_from: develop\n- commit_pattern: feat({ticket_id}): {description}\n",
        encoding="utf-8",
    )
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "config.md").write_text("hidden config", encoding="utf-8")
    return tmp_path


def test_search_finds_dotfile_at_vault_root(vault):
    tool = ObsidianTool(vault_path=str(vault))
    result = tool.execute(query=".autopilot-rules.md")
    assert result.success
    assert any(".autopilot-rules.md" in n["path"] for n in result.data)


def test_search_skips_files_inside_hidden_directories(vault):
    tool = ObsidianTool(vault_path=str(vault))
    result = tool.execute(query="hidden config")
    assert result.success
    assert not any(".obsidian" in n["path"] for n in result.data)


def test_search_finds_regular_notes(vault):
    tool = ObsidianTool(vault_path=str(vault))
    result = tool.execute(query="feature")
    assert result.success
    assert any(n["title"] == "note" for n in result.data)