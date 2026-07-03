"""Unit tests for ConfigCommand use case.

Validates: Requirement 1.4

WHEN the user executes `autopilot config`, THE CLI SHALL display the current
configuration values in YAML format to stdout.
"""

import yaml

from autopilot.application.use_cases.config_command import ConfigCommand
from autopilot.domain.entities.config import Config


def test_config_command_returns_yaml_string():
    """ConfigCommand.execute() returns a valid YAML string."""
    config = Config(vault_location="/tmp/vault", workspace_location="/tmp/workspace")
    cmd = ConfigCommand(config=config)

    result = cmd.execute()

    # Result should be parseable YAML
    parsed = yaml.safe_load(result)
    assert isinstance(parsed, dict)


def test_config_command_contains_all_fields():
    """ConfigCommand output includes all Config fields."""
    config = Config(
        vault_location="/home/user/vault",
        workspace_location="/home/user/workspace",
        available_mcps=["mcp1", "mcp2"],
        llm_model="gpt-4",
        llm_provider="openai",
        timeout_seconds=120,
        max_retries=5,
        base_delay=3.0,
        backoff_multiplier=1.5,
        verbosity="verbose",
    )
    cmd = ConfigCommand(config=config)

    result = cmd.execute()
    parsed = yaml.safe_load(result)

    assert parsed["vault_location"] == "/home/user/vault"
    assert parsed["workspace_location"] == "/home/user/workspace"
    assert parsed["available_mcps"] == ["mcp1", "mcp2"]
    assert parsed["llm_model"] == "gpt-4"
    assert parsed["llm_provider"] == "openai"
    assert parsed["timeout_seconds"] == 120
    assert parsed["max_retries"] == 5
    assert parsed["base_delay"] == 3.0
    assert parsed["backoff_multiplier"] == 1.5
    assert parsed["verbosity"] == "verbose"


def test_config_command_default_values():
    """ConfigCommand correctly renders default Config values."""
    config = Config(vault_location="/vault", workspace_location="/ws")
    cmd = ConfigCommand(config=config)

    result = cmd.execute()
    parsed = yaml.safe_load(result)

    assert parsed["available_mcps"] == []
    assert parsed["llm_model"] == ""
    assert parsed["llm_provider"] == ""
    assert parsed["timeout_seconds"] == 60
    assert parsed["max_retries"] == 3
    assert parsed["base_delay"] == 2.0
    assert parsed["backoff_multiplier"] == 2.0
    assert parsed["verbosity"] == "normal"
