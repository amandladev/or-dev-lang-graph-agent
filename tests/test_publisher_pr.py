"""Tests for Publisher pull request creation driven by vault rules."""

import subprocess
from unittest.mock import patch

import pytest

from autopilot.application.registries.tool_registry import ToolRegistry
from autopilot.domain.interfaces.tool_interface import ToolResult
from autopilot.infrastructure.agents.publisher import PublisherAgent


class RecordingGitHubTool:
    name = "github"
    input_schema = {"action": str}
    output_schema = {"result": dict}

    def __init__(self, pr_url="https://github.com/acme/repo/pull/99", success=True):
        self.calls = []
        self._pr_url = pr_url
        self._success = success

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return ToolResult(
            success=self._success,
            data={"pr_url": self._pr_url, "repo": "acme/repo"},
        )


class FakeRulesProvider:
    def __init__(self, rules):
        self._rules = rules

    def get(self):
        return self._rules


def _creator(github_tool):
    return PublisherAgent(
        tool_registry=ToolRegistry(),
        rules_provider=None,
    ), github_tool


def _publisher_with_rules(rules, github_tool):
    registry = ToolRegistry()
    registry.register(github_tool)
    agent = PublisherAgent(tool_registry=registry, rules_provider=None)
    return agent


@pytest.fixture
def published_workflow():
    """Sandbox publisher: real agent, mocked git workflow and rules provider."""
    workspace = {
        "path": "/tmp/worktree/d-1",
        "branch": "feature/d-1",
    }

    def factory(rules, github_tool, monkeypatch):
        registry = ToolRegistry()
        registry.register(github_tool)
        agent = PublisherAgent(tool_registry=registry, rules_provider=None)
        state = {
            "ticket": {"id": "D-1", "title": "Implement feature"},
            "evidence": [],
            "modified_files": ["src/main.py"],
            "workspace": workspace,
        }
        monkeypatch.setattr(agent, "_load_rules", lambda: rules)
        monkeypatch.setattr(
            agent, "_execute_git_workflow",
            lambda *a, **k: {"operations": [{"command": ["git", "push"], "success": True, "output": ""}]},
        )
        monkeypatch.setattr(agent, "_update_jira", lambda *a, **k: {"skipped": True})
        return agent, state

    return factory, workspace


def test_no_create_pr_rule_skips_pr(published_workflow, monkeypatch):
    factory, _ = published_workflow
    github = RecordingGitHubTool()
    rules = {
        "source": "vault",
        "branch_from": "develop",
        "branch_pattern": "feature/{ticket_id}",
        "commit_pattern": "feat({ticket_id}): {description}",
        "push_remote": "origin",
        "create_pr": False,
        "pr_base": "",
    }
    agent, state = factory(rules, github, monkeypatch)
    metrics = agent.execute(state)["metrics"]

    assert metrics["pull_request"] == {
        "skipped": True,
        "reason": "No create_pr rule configured",
    }
    assert github.calls == []


def test_create_pr_rule_opens_pr(published_workflow, monkeypatch):
    factory, _ = published_workflow
    github = RecordingGitHubTool()
    rules = {
        "source": "vault",
        "branch_from": "develop",
        "branch_pattern": "feature/{ticket_id}",
        "commit_pattern": "feat({ticket_id}): {description}",
        "push_remote": "origin",
        "create_pr": True,
        "pr_base": "develop",
    }
    agent, state = factory(rules, github, monkeypatch)
    metrics = agent.execute(state)["metrics"]

    pr = metrics["pull_request"]
    assert pr["success"] is True
    assert pr["pr_url"] == "https://github.com/acme/repo/pull/99"
    call = github.calls[0]
    assert call["action"] == "create_pr"
    assert call["head"] == "feature/d-1"
    assert call["base"] == "develop"
    assert call["title"] == "feat(D-1): Implement feature"


def test_pr_failure_does_not_fail_publishing(published_workflow, monkeypatch):
    factory, workspace = published_workflow
    github = RecordingGitHubTool(success=False, pr_url="")
    rules = {"source": "vault", "branch_from": "develop", "create_pr": True,
             "commit_pattern": "feat({ticket_id}): {description}", "pr_base": "develop"}
    agent, state = factory(rules, github, monkeypatch)

    result = agent.execute({**state})
    assert result["metrics"]["published"] is True
    pr = result["metrics"]["pull_request"]
    assert pr["success"] is False
