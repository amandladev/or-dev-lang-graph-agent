"""Property 3: Environment variable override.

Validates: Requirements 6.6

For any config field and corresponding environment variable
AUTOPILOT_<FIELD_NAME>, the environment variable value takes precedence
over the YAML file value when both are present.
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.adapters.yaml_config_loader import YAMLConfigLoader


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty strings for required path fields (vault_location, workspace_location)
non_empty_path_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="/._-",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

# Generic string fields (llm_model max 100 chars, llm_provider max 50 chars)
# Using yaml.safe_dump to write config, so any printable string is safe.
_yaml_safe_chars = st.characters(
    whitelist_categories=("L", "N", "P"),
)

llm_model_strategy = st.text(
    alphabet=_yaml_safe_chars,
    min_size=0,
    max_size=50,
)

llm_provider_strategy = st.text(
    alphabet=_yaml_safe_chars,
    min_size=0,
    max_size=30,
)

# Numeric fields with valid ranges
timeout_strategy = st.integers(min_value=1, max_value=600)
max_retries_strategy = st.integers(min_value=0, max_value=10)

# Verbosity must be one of the valid values
verbosity_strategy = st.sampled_from(["quiet", "normal", "verbose"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Environment variables that our tests set — we clean them up after each test
_ENV_VARS = [
    "AUTOPILOT_VAULT_LOCATION",
    "AUTOPILOT_WORKSPACE_LOCATION",
    "AUTOPILOT_LLM_MODEL",
    "AUTOPILOT_LLM_PROVIDER",
    "AUTOPILOT_TIMEOUT_SECONDS",
    "AUTOPILOT_MAX_RETRIES",
    "AUTOPILOT_VERBOSITY",
]


def _cleanup_env():
    """Remove all AUTOPILOT_ env vars used in tests."""
    for var in _ENV_VARS:
        os.environ.pop(var, None)


def _write_config(tmp_dir: str, content: str) -> str:
    """Write config content to a temp file and return the path."""
    config_path = os.path.join(tmp_dir, "config.yaml")
    Path(config_path).write_text(content)
    return config_path


def _write_config_dict(tmp_dir: str, data: dict) -> str:
    """Write config as a dict (via yaml.safe_dump) and return the path."""
    config_path = os.path.join(tmp_dir, "config.yaml")
    Path(config_path).write_text(yaml.safe_dump(data, default_flow_style=False))
    return config_path


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    yaml_vault=non_empty_path_strategy,
    yaml_workspace=non_empty_path_strategy,
    env_vault=non_empty_path_strategy,
    env_workspace=non_empty_path_strategy,
)
def test_env_var_overrides_vault_and_workspace(
    yaml_vault,
    yaml_workspace,
    env_vault,
    env_workspace,
):
    """**Validates: Requirements 6.6**

    Property 3: Environment variables AUTOPILOT_VAULT_LOCATION and
    AUTOPILOT_WORKSPACE_LOCATION override YAML values.
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        config_path = _write_config(
            tmp_dir,
            f"vault_location: {yaml_vault}\n"
            f"workspace_location: {yaml_workspace}\n",
        )

        os.environ["AUTOPILOT_VAULT_LOCATION"] = env_vault
        os.environ["AUTOPILOT_WORKSPACE_LOCATION"] = env_workspace

        loader = YAMLConfigLoader()
        config = loader.load(config_path)

        assert config.vault_location == env_vault, (
            f"Expected vault_location='{env_vault}' from env var, "
            f"got '{config.vault_location}'"
        )
        assert config.workspace_location == env_workspace, (
            f"Expected workspace_location='{env_workspace}' from env var, "
            f"got '{config.workspace_location}'"
        )
    finally:
        _cleanup_env()


@settings(max_examples=100)
@given(
    yaml_model=llm_model_strategy,
    yaml_provider=llm_provider_strategy,
    env_model=llm_model_strategy,
    env_provider=llm_provider_strategy,
)
def test_env_var_overrides_llm_fields(
    yaml_model,
    yaml_provider,
    env_model,
    env_provider,
):
    """**Validates: Requirements 6.6**

    Property 3: Environment variables AUTOPILOT_LLM_MODEL and
    AUTOPILOT_LLM_PROVIDER override YAML values.
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        config_path = _write_config_dict(
            tmp_dir,
            {
                "vault_location": "/some/vault",
                "workspace_location": "/some/workspace",
                "llm_model": yaml_model,
                "llm_provider": yaml_provider,
            },
        )

        os.environ["AUTOPILOT_VAULT_LOCATION"] = "/some/vault"
        os.environ["AUTOPILOT_WORKSPACE_LOCATION"] = "/some/workspace"
        os.environ["AUTOPILOT_LLM_MODEL"] = env_model
        os.environ["AUTOPILOT_LLM_PROVIDER"] = env_provider

        loader = YAMLConfigLoader()
        config = loader.load(config_path)

        assert config.llm_model == env_model, (
            f"Expected llm_model='{env_model}' from env var, "
            f"got '{config.llm_model}'"
        )
        assert config.llm_provider == env_provider, (
            f"Expected llm_provider='{env_provider}' from env var, "
            f"got '{config.llm_provider}'"
        )
    finally:
        _cleanup_env()


@settings(max_examples=100)
@given(
    yaml_timeout=timeout_strategy,
    yaml_retries=max_retries_strategy,
    env_timeout=timeout_strategy,
    env_retries=max_retries_strategy,
)
def test_env_var_overrides_numeric_fields(
    yaml_timeout,
    yaml_retries,
    env_timeout,
    env_retries,
):
    """**Validates: Requirements 6.6**

    Property 3: Environment variables AUTOPILOT_TIMEOUT_SECONDS and
    AUTOPILOT_MAX_RETRIES override YAML numeric values.
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        config_path = _write_config(
            tmp_dir,
            f"vault_location: /some/vault\n"
            f"workspace_location: /some/workspace\n"
            f"timeout_seconds: {yaml_timeout}\n"
            f"max_retries: {yaml_retries}\n",
        )

        os.environ["AUTOPILOT_VAULT_LOCATION"] = "/some/vault"
        os.environ["AUTOPILOT_WORKSPACE_LOCATION"] = "/some/workspace"
        os.environ["AUTOPILOT_TIMEOUT_SECONDS"] = str(env_timeout)
        os.environ["AUTOPILOT_MAX_RETRIES"] = str(env_retries)

        loader = YAMLConfigLoader()
        config = loader.load(config_path)

        assert config.timeout_seconds == env_timeout, (
            f"Expected timeout_seconds={env_timeout} from env var, "
            f"got {config.timeout_seconds}"
        )
        assert config.max_retries == env_retries, (
            f"Expected max_retries={env_retries} from env var, "
            f"got {config.max_retries}"
        )
    finally:
        _cleanup_env()


@settings(max_examples=100)
@given(
    yaml_verbosity=verbosity_strategy,
    env_verbosity=verbosity_strategy,
)
def test_env_var_overrides_verbosity(
    yaml_verbosity,
    env_verbosity,
):
    """**Validates: Requirements 6.6**

    Property 3: Environment variable AUTOPILOT_VERBOSITY overrides YAML value.
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        config_path = _write_config(
            tmp_dir,
            f"vault_location: /some/vault\n"
            f"workspace_location: /some/workspace\n"
            f"verbosity: {yaml_verbosity}\n",
        )

        os.environ["AUTOPILOT_VAULT_LOCATION"] = "/some/vault"
        os.environ["AUTOPILOT_WORKSPACE_LOCATION"] = "/some/workspace"
        os.environ["AUTOPILOT_VERBOSITY"] = env_verbosity

        loader = YAMLConfigLoader()
        config = loader.load(config_path)

        assert config.verbosity == env_verbosity, (
            f"Expected verbosity='{env_verbosity}' from env var, "
            f"got '{config.verbosity}'"
        )
    finally:
        _cleanup_env()
