"""ConfigCommand use case for displaying current configuration."""

from dataclasses import asdict

import yaml

from autopilot.domain.entities.config import Config


class ConfigCommand:
    """Use case that formats the current configuration as YAML for display.

    Accepts a Config entity and produces a YAML-formatted string representation.
    """

    def __init__(self, config: Config) -> None:
        """Initialize with the current application configuration.

        Args:
            config: The Config entity from the domain layer.
        """
        self._config = config

    def execute(self) -> str:
        """Convert the configuration to a YAML-formatted string.

        Returns:
            A YAML string representation of the current configuration.
        """
        config_dict = asdict(self._config)
        return yaml.safe_dump(config_dict, default_flow_style=False, sort_keys=False)
