"""Unit tests for the GitHub tool PR creation."""

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from autopilot.infrastructure.tools.github_tool import GitHubTool


@pytest.fixture
def gh_mocks():
    """Tool with mocked remote resolution and gh execution."""
    tool = GitHubTool()
    state = SimpleNamespace(remote="", repo_url="", gh_cmd=[], gh_stdout="", gh_returncode=0)

    def fake_remote(cwd):
        return state.remote

    def fake_run(cmd, cwd):
        state.gh_cmd = list(cmd)
        return subprocess.CompletedProcess(
            cmd, state.gh_returncode, stdout=state.gh_stdout, stderr=""
        )

    with patch.object(tool, "_remote_url", side_effect=fake_remote):
        with patch.object(tool, "run", side_effect=fake_run):
            yield tool, state


def test_unsupported_action(gh_mocks):
    tool, _ = gh_mocks
    result = tool.execute(action="rebase", cwd="/tmp")
    assert result.success is False
    assert "Unsupported" in result.error


def test_missing_remote(gh_mocks):
    tool, state = gh_mocks
    state.remote = None
    result = tool.execute(action="create_pr", cwd="/tmp", head="a", base="b", title="t", body="")
    assert result.success is False
    assert "remote" in result.error.lower()


def test_non_github_remote_is_skipped(gh_mocks):
    tool, state = gh_mocks
    state.remote = "gitlab.com:foo/bar.git"
    result = tool.execute(action="create_pr", cwd="/tmp", head="a", base="b", title="t", body="")
    assert result.success is False
    assert result.data["skipped"] is True


def test_ssh_alias_remote_resolves_owner_name(gh_mocks):
    tool, state = gh_mocks
    state.remote = "git@github.com:amandladev/autopilot-demo.git"
    state.gh_stdout = "https://github.com/amandladev/autopilot-demo/pull/1\n"
    result = tool.execute(
        action="create_pr", cwd="/tmp", head="feature/x-1", base="develop",
        title="feat(X-1): t", body="",
    )
    assert result.success is True
    assert result.data["pr_url"].endswith("pull/1")
    assert "--repo" in state.gh_cmd
    assert state.gh_cmd[state.gh_cmd.index("--repo") + 1] == "amandladev/autopilot-demo"
    assert state.gh_cmd[state.gh_cmd.index("--head") + 1] == "feature/x-1"


def test_https_remote_resolves_owner_name(gh_mocks):
    tool, state = gh_mocks
    state.remote = "https://github.com/amandladev/autopilot-demo.git"
    state.gh_stdout = "https://github.com/amandladev/autopilot-demo/pull/2"
    result = tool.execute(
        action="create_pr", cwd="/tmp", head="feature/x-2", base="develop",
        title="t", body="",
    )
    assert result.success is True
    assert state.gh_cmd[state.gh_cmd.index("--repo") + 1] == "amandladev/autopilot-demo"


def test_ssh_enterprise_host(gh_mocks):
    tool, state = gh_mocks
    state.remote = "git@github.proveedor.pe:amandladev/autopilot-demo.git"
    state.gh_stdout = "url"
    result = tool.execute(
        action="create_pr", cwd="/tmp", head="feature/x-3", base="develop",
        title="t", body="",
    )
    assert result.success is False
    assert result.data["skipped"] is True


def test_gh_failure_returns_error(gh_mocks):
    tool, state = gh_mocks
    state.remote = "git@github.com:amandladev/autopilot-demo.git"
    state.gh_returncode = 1
    state.gh_stdout = ""
    result = tool.execute(
        action="create_pr", cwd="/tmp", head="a", base="b", title="t", body=""
    )
    assert result.success is False
    assert "gh pr create" in result.error
