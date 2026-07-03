"""Property 2: Config validation accepts valid values and rejects invalid values.

Validates: Requirements 6.2, 6.5

For any configuration field value within the defined constraints
(MCPs ≤ 20, model ≤ 100 chars, provider ≤ 50 chars, timeout in [1, 600],
max_retries in [0, 10]), Config accepts the values without error.

For any value outside those constraints, Config raises ValueError indicating
the field name, provided value, and expected constraint.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.domain.entities.config import Config


# ---------------------------------------------------------------------------
# Strategies for valid values
# ---------------------------------------------------------------------------

# Valid MCP lists: 0 to 20 entries
valid_mcps_strategy = st.lists(
    st.text(min_size=1, max_size=30),
    min_size=0,
    max_size=20,
)

# Valid model strings: 0 to 100 characters
valid_model_strategy = st.text(min_size=0, max_size=100)

# Valid provider strings: 0 to 50 characters
valid_provider_strategy = st.text(min_size=0, max_size=50)

# Valid timeout: integer in [1, 600]
valid_timeout_strategy = st.integers(min_value=1, max_value=600)

# Valid max_retries: integer in [0, 10]
valid_max_retries_strategy = st.integers(min_value=0, max_value=10)


# ---------------------------------------------------------------------------
# Strategies for invalid values
# ---------------------------------------------------------------------------

# Invalid MCP lists: 21+ entries
invalid_mcps_strategy = st.lists(
    st.text(min_size=1, max_size=10),
    min_size=21,
    max_size=30,
)

# Invalid model strings: 101+ characters
invalid_model_strategy = st.text(min_size=101, max_size=200)

# Invalid provider strings: 51+ characters
invalid_provider_strategy = st.text(min_size=51, max_size=100)

# Invalid timeout: outside [1, 600]
invalid_timeout_strategy = st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=601),
)

# Invalid max_retries: outside [0, 10]
invalid_max_retries_strategy = st.one_of(
    st.integers(max_value=-1),
    st.integers(min_value=11),
)


# ---------------------------------------------------------------------------
# Helper to build a Config with specific overrides
# ---------------------------------------------------------------------------

def make_config(**overrides) -> Config:
    """Create a Config instance with sensible defaults and given overrides."""
    defaults = {
        "vault_location": "/tmp/vault",
        "workspace_location": "/tmp/workspace",
        "available_mcps": [],
        "llm_model": "",
        "llm_provider": "",
        "timeout_seconds": 60,
        "max_retries": 3,
    }
    defaults.update(overrides)
    return Config(**defaults)


# ---------------------------------------------------------------------------
# Property-Based Tests: Valid values are accepted
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    mcps=valid_mcps_strategy,
    model=valid_model_strategy,
    provider=valid_provider_strategy,
    timeout=valid_timeout_strategy,
    retries=valid_max_retries_strategy,
)
def test_valid_config_accepted(
    mcps: list[str],
    model: str,
    provider: str,
    timeout: int,
    retries: int,
):
    """**Validates: Requirements 6.2, 6.5**

    Property 2: For any configuration field value within the defined constraints,
    Config accepts the values without error.
    """
    # Should not raise any exception
    config = make_config(
        available_mcps=mcps,
        llm_model=model,
        llm_provider=provider,
        timeout_seconds=timeout,
        max_retries=retries,
    )

    # Verify values are stored correctly
    assert config.available_mcps == mcps
    assert config.llm_model == model
    assert config.llm_provider == provider
    assert config.timeout_seconds == timeout
    assert config.max_retries == retries


# ---------------------------------------------------------------------------
# Property-Based Tests: Invalid values are rejected with proper error messages
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(mcps=invalid_mcps_strategy)
def test_invalid_mcps_raises_value_error(mcps: list[str]):
    """**Validates: Requirements 6.2, 6.5**

    Property 2: For MCPs with more than 20 entries, Config raises ValueError
    indicating the field name and constraint.
    """
    with pytest.raises(ValueError) as exc_info:
        make_config(available_mcps=mcps)

    error_msg = str(exc_info.value)
    assert "available_mcps" in error_msg
    assert str(len(mcps)) in error_msg
    assert "20" in error_msg


@settings(max_examples=100)
@given(model=invalid_model_strategy)
def test_invalid_model_raises_value_error(model: str):
    """**Validates: Requirements 6.2, 6.5**

    Property 2: For model strings longer than 100 characters, Config raises
    ValueError indicating the field name and constraint.
    """
    with pytest.raises(ValueError) as exc_info:
        make_config(llm_model=model)

    error_msg = str(exc_info.value)
    assert "llm_model" in error_msg
    assert str(len(model)) in error_msg
    assert "100" in error_msg


@settings(max_examples=100)
@given(provider=invalid_provider_strategy)
def test_invalid_provider_raises_value_error(provider: str):
    """**Validates: Requirements 6.2, 6.5**

    Property 2: For provider strings longer than 50 characters, Config raises
    ValueError indicating the field name and constraint.
    """
    with pytest.raises(ValueError) as exc_info:
        make_config(llm_provider=provider)

    error_msg = str(exc_info.value)
    assert "llm_provider" in error_msg
    assert str(len(provider)) in error_msg
    assert "50" in error_msg


@settings(max_examples=100)
@given(timeout=invalid_timeout_strategy)
def test_invalid_timeout_raises_value_error(timeout: int):
    """**Validates: Requirements 6.2, 6.5**

    Property 2: For timeout values outside [1, 600], Config raises ValueError
    indicating the field name, provided value, and expected constraint.
    """
    with pytest.raises(ValueError) as exc_info:
        make_config(timeout_seconds=timeout)

    error_msg = str(exc_info.value)
    assert "timeout_seconds" in error_msg
    assert str(timeout) in error_msg
    assert "1" in error_msg and "600" in error_msg


@settings(max_examples=100)
@given(retries=invalid_max_retries_strategy)
def test_invalid_max_retries_raises_value_error(retries: int):
    """**Validates: Requirements 6.2, 6.5**

    Property 2: For max_retries values outside [0, 10], Config raises ValueError
    indicating the field name, provided value, and expected constraint.
    """
    with pytest.raises(ValueError) as exc_info:
        make_config(max_retries=retries)

    error_msg = str(exc_info.value)
    assert "max_retries" in error_msg
    assert str(retries) in error_msg
    assert "0" in error_msg and "10" in error_msg
