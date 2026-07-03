"""Serializer interface protocol for the domain layer."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SerializerInterface(Protocol):
    """Protocol for state serialization and deserialization."""

    def serialize(self, state: Any) -> str:
        """
        Serialize a state object to a string representation.

        Args:
            state: The state object to serialize.

        Returns:
            String representation of the state.
        """
        ...

    def deserialize(self, data: str) -> Any:
        """
        Deserialize a string representation back to a state object.

        Args:
            data: The string representation to deserialize.

        Returns:
            The reconstructed state object.
        """
        ...
