"""Config loader interface protocol for the domain layer."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConfigLoaderInterface(Protocol):
    """Protocol for loading application configuration."""

    def load(self, path: str) -> Any:
        """
        Load configuration from the specified path.

        Args:
            path: Filesystem path to the configuration file.

        Returns:
            The loaded configuration object.
        """
        ...
