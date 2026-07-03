"""YAML configuration loader implementation."""

import os
import sys
from pathlib import Path

import yaml

from autopilot.domain.entities.config import Config


# Default config YAML content with inline comments
_DEFAULT_CONFIG = """\
# Autopilot Configuration
# Override any field with environment variable: AUTOPILOT_<FIELD_NAME>

# Path to your Obsidian vault (required)
vault_location: ""

# Path to the workspace directory (required)
workspace_location: ""

# List of available MCP servers (max 20 entries)
available_mcps: []

# LLM model name (max 100 characters)
# Override: AUTOPILOT_LLM_MODEL
llm_model: ""

# LLM provider name (max 50 characters)
# Override: AUTOPILOT_LLM_PROVIDER
llm_provider: ""

# Timeout for operations in seconds (range: 1-600)
# Override: AUTOPILOT_TIMEOUT_SECONDS
timeout_seconds: 60

# Maximum number of retries on retryable errors (range: 0-10)
# Override: AUTOPILOT_MAX_RETRIES
max_retries: 3

# Base delay between retries in seconds
# Override: AUTOPILOT_BASE_DELAY
base_delay: 2.0

# Backoff multiplier applied on each successive retry
# Override: AUTOPILOT_BACKOFF_MULTIPLIER
backoff_multiplier: 2.0

# Logging verbosity: quiet, normal, or verbose
# Override: AUTOPILOT_VERBOSITY
verbosity: normal
"""

# Fields that must be present and non-empty in the config
_REQUIRED_FIELDS = ("vault_location", "workspace_location")

# Mapping from config field name to environment variable name
_ENV_VAR_PREFIX = "AUTOPILOT_"


class YAMLConfigLoader:
    """Loads application configuration from a YAML file.

    Implements ConfigLoaderInterface protocol.
    """

    def load(self, path: str) -> Config:
        """Load configuration from a YAML file.

        If the file does not exist, creates a default config with inline
        comments and raises SystemExit prompting the user to review it.

        Applies environment variable overrides using the pattern
        AUTOPILOT_<FIELD_NAME> (uppercase).

        Args:
            path: Filesystem path to the YAML configuration file.

        Returns:
            A validated Config instance.

        Raises:
            SystemExit: If the file does not exist (after creating default),
                or if required fields are missing, or if validation fails.
        """
        config_path = Path(path)

        # If config file doesn't exist, create default and exit
        if not config_path.exists():
            self._create_default_config(config_path)
            print(
                f"Created default configuration at '{config_path}'. "
                f"Please review and update required fields before running again.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        # Parse YAML
        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            print(f"Failed to parse config file '{config_path}': {e}", file=sys.stderr)
            raise SystemExit(1)

        if not isinstance(data, dict):
            print(
                f"Config file '{config_path}' must contain a YAML mapping.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        # Apply environment variable overrides
        data = self._apply_env_overrides(data)

        # Check required fields
        for field_name in _REQUIRED_FIELDS:
            if field_name not in data or not data[field_name]:
                print(
                    f"Missing required configuration field: {field_name}",
                    file=sys.stderr,
                )
                raise SystemExit(1)

        # Build Config (validation happens in __post_init__)
        try:
            config = Config(
                vault_location=str(data.get("vault_location", "")),
                workspace_location=str(data.get("workspace_location", "")),
                available_mcps=data.get("available_mcps", []),
                llm_model=str(data.get("llm_model", "")),
                llm_provider=str(data.get("llm_provider", "")),
                timeout_seconds=int(data.get("timeout_seconds", 60)),
                max_retries=int(data.get("max_retries", 3)),
                base_delay=float(data.get("base_delay", 2.0)),
                backoff_multiplier=float(data.get("backoff_multiplier", 2.0)),
                verbosity=str(data.get("verbosity", "normal")),
            )
        except (ValueError, TypeError) as e:
            print(f"Configuration validation error: {e}", file=sys.stderr)
            raise SystemExit(1)

        return config

    def _create_default_config(self, config_path: Path) -> None:
        """Create a default configuration file with inline comments."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            f.write(_DEFAULT_CONFIG)

    def _apply_env_overrides(self, data: dict) -> dict:
        """Apply environment variable overrides to config data.

        For each config field, checks for AUTOPILOT_<FIELD_NAME> env var.
        For list fields (available_mcps), the env var value is split by commas.
        For numeric fields, conversion happens later during Config construction.

        Args:
            data: The parsed YAML data dictionary.

        Returns:
            The data dictionary with environment variable overrides applied.
        """
        # Define all known config fields and their types for proper parsing
        field_types = {
            "vault_location": str,
            "workspace_location": str,
            "available_mcps": list,
            "llm_model": str,
            "llm_provider": str,
            "timeout_seconds": int,
            "max_retries": int,
            "base_delay": float,
            "backoff_multiplier": float,
            "verbosity": str,
        }

        for field_name, field_type in field_types.items():
            env_var = f"{_ENV_VAR_PREFIX}{field_name.upper()}"
            env_value = os.environ.get(env_var)
            if env_value is not None:
                data[field_name] = self._parse_env_value(
                    env_var, env_value, field_type
                )

        return data

    def _parse_env_value(self, env_var: str, env_value: str, field_type: type) -> object:
        """Parse an environment variable value into the expected type.

        Args:
            env_var: The environment variable name (for error messages).
            env_value: The raw string value from the environment.
            field_type: The expected Python type for the config field.

        Returns:
            The parsed value in the correct type.

        Raises:
            SystemExit: If numeric conversion fails.
        """
        if field_type is list:
            return [
                item.strip() for item in env_value.split(",") if item.strip()
            ]

        if field_type is int:
            try:
                return int(env_value)
            except ValueError:
                print(
                    f"Invalid integer value for {env_var}: '{env_value}'",
                    file=sys.stderr,
                )
                raise SystemExit(1)

        if field_type is float:
            try:
                return float(env_value)
            except ValueError:
                print(
                    f"Invalid float value for {env_var}: '{env_value}'",
                    file=sys.stderr,
                )
                raise SystemExit(1)

        return env_value
