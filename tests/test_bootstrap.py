"""Smoke tests for the dependency-injection bootstrap module.

Covers Requirement 10 of core-orchestration-test-coverage.
"""

import pytest

from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.infrastructure.bootstrap import create_application


@pytest.fixture
def bootstrap_config_path(tmp_path):
    config_file = tmp_path / "bootstrap_test_config.yaml"
    config_file.write_text(
        f"""
vault_location: "{tmp_path / 'vault'}"
workspace_location: "{tmp_path / 'workspace'}"
available_mcps: []
llm_model: "anthropic/claude-sonnet-4-20250514"
llm_provider: "anthropic"
timeout_seconds: 60
max_retries: 3
base_delay: 2.0
backoff_multiplier: 2.0
verbosity: quiet
""".strip()
    )
    return str(config_file)


# ---------------------------------------------------------------------------
# 10.1-10.3: create_application with valid fixture -> non-None attributes,
# correct type, no exception
# Validates: Requirements 10.1, 10.2, 10.3
# ---------------------------------------------------------------------------


def test_create_application_wires_all_components_without_error(bootstrap_config_path):
    app = create_application(bootstrap_config_path)

    assert app.config is not None
    assert app.engine is not None
    assert app.work_command is not None
    assert app.resume_command is not None
    assert app.config_command is not None
    assert app.knowledge_engine is not None
    assert app.experience_builder is not None
    assert app.run_record_store is not None
    assert app.ledger is not None
    assert app.ledger_committer is not None


def test_create_application_engine_is_orchestration_engine_instance(bootstrap_config_path):
    app = create_application(bootstrap_config_path)

    assert isinstance(app.engine, OrchestrationEngine)


# ---------------------------------------------------------------------------
# 10.4: create_application with nonexistent config path -> SystemExit
# Validates: Requirements 10.4
# ---------------------------------------------------------------------------


def test_create_application_nonexistent_config_path_raises_system_exit(tmp_path):
    nonexistent_path = str(tmp_path / "does_not_exist.yaml")

    with pytest.raises(SystemExit):
        create_application(nonexistent_path)
