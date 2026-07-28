"""JSON serializer for WorkflowState persistence."""

import dataclasses
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from autopilot.domain.entities.workflow_state import WorkflowState
from autopilot.domain.value_objects.error_record import ErrorRecord, ErrorType
from autopilot.domain.value_objects.evidence import EvidenceItem
from autopilot.domain.value_objects.log_entry import LogEntry, StepStatus
from autopilot.infrastructure.persistence.atomic_write import atomic_write_text
from autopilot.infrastructure.persistence.file_lock import LedgerLock, lock_path_for


class DeserializationError(Exception):
    """Raised when deserialization fails with diagnostic info."""

    def __init__(
        self,
        message: str,
        failure_type: str,
        field_path: str | None = None,
        offset: int | None = None,
    ) -> None:
        self.failure_type = failure_type
        self.field_path = field_path
        self.offset = offset
        detail = f"[{failure_type}]"
        if field_path:
            detail += f" at field '{field_path}'"
        if offset is not None:
            detail += f" at offset {offset}"
        super().__init__(f"{detail}: {message}")


class _WorkflowStateEncoder(json.JSONEncoder):
    """Custom JSON encoder handling datetime, enums, and dataclasses."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return {"__type__": "datetime", "value": obj.isoformat()}
        if isinstance(obj, Enum):
            return {
                "__type__": "enum",
                "enum_class": f"{type(obj).__module__}.{type(obj).__qualname__}",
                "value": obj.value,
            }
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return {
                "__type__": "dataclass",
                "class": f"{type(obj).__module__}.{type(obj).__qualname__}",
                "fields": dataclasses.asdict(obj),
            }
        return super().default(obj)


# Registry mapping class qualified paths to their constructors for deserialization.
_DATACLASS_REGISTRY: dict[str, type] = {
    f"{cls.__module__}.{cls.__qualname__}": cls
    for cls in (LogEntry, EvidenceItem, ErrorRecord)
}

_ENUM_REGISTRY: dict[str, type[Enum]] = {
    f"{cls.__module__}.{cls.__qualname__}": cls
    for cls in (StepStatus, ErrorType)
}


def _decode_datetime(obj: dict[str, Any], path: str) -> datetime:
    """Decode a tagged datetime object."""
    try:
        return datetime.fromisoformat(obj["value"])
    except (ValueError, KeyError) as e:
        raise DeserializationError(
            f"Invalid datetime value: {e}",
            failure_type="schema_violation",
            field_path=path,
        ) from e


def _decode_enum(obj: dict[str, Any], path: str) -> Enum:
    """Decode a tagged enum object."""
    enum_class_name = obj.get("enum_class", "")
    enum_cls = _ENUM_REGISTRY.get(enum_class_name)
    if enum_cls is None:
        raise DeserializationError(
            f"Unknown enum class: {enum_class_name}",
            failure_type="schema_violation",
            field_path=path,
        )
    try:
        return enum_cls(obj["value"])
    except (ValueError, KeyError) as e:
        raise DeserializationError(
            f"Invalid enum value: {e}",
            failure_type="schema_violation",
            field_path=path,
        ) from e


def _decode_dataclass(obj: dict[str, Any], path: str) -> Any:
    """Decode a tagged dataclass object."""
    class_name = obj.get("class", "")
    dc_cls = _DATACLASS_REGISTRY.get(class_name)
    if dc_cls is None:
        raise DeserializationError(
            f"Unknown dataclass: {class_name}",
            failure_type="schema_violation",
            field_path=path,
        )
    fields_data = obj.get("fields", {})
    decoded_fields = {}
    for key, value in fields_data.items():
        field_path = f"{path}.{key}" if path else key
        decoded_fields[key] = _recursive_decode(value, field_path)
    try:
        return dc_cls(**decoded_fields)
    except TypeError as e:
        raise DeserializationError(
            f"Cannot construct {class_name}: {e}",
            failure_type="schema_violation",
            field_path=path,
        ) from e


def _decode_object(obj: dict[str, Any], path: str = "") -> Any:
    """Recursively decode tagged objects back to their original types."""
    type_tag = obj.get("__type__")

    if type_tag == "datetime":
        return _decode_datetime(obj, path)

    if type_tag == "enum":
        return _decode_enum(obj, path)

    if type_tag == "dataclass":
        return _decode_dataclass(obj, path)

    # Regular dict — decode values recursively
    return {k: _recursive_decode(v, f"{path}.{k}" if path else k) for k, v in obj.items()}


def _recursive_decode(value: Any, path: str = "") -> Any:
    """Recursively walk a decoded JSON structure and restore typed objects."""
    if isinstance(value, dict):
        return _decode_object(value, path)
    if isinstance(value, list):
        return [_recursive_decode(item, f"{path}[{i}]") for i, item in enumerate(value)]
    return value


class JSONSerializer:
    """Serializes and deserializes WorkflowState to/from JSON.

    Implements the SerializerInterface protocol from the domain layer.
    """

    def __init__(self, storage_path: str | None = None) -> None:
        """Initialize the serializer.

        Args:
            storage_path: Optional base directory for file persistence.
        """
        self._storage_path = Path(storage_path) if storage_path else None

    def serialize(self, state: WorkflowState) -> str:
        """Serialize a WorkflowState to a JSON string.

        Args:
            state: The WorkflowState object to serialize.

        Returns:
            A JSON string representation of the state.
        """
        data = self._prepare_for_json(state)
        return json.dumps(data, cls=_WorkflowStateEncoder, indent=2)

    def deserialize(self, data: str) -> WorkflowState:
        """Deserialize a JSON string back to a WorkflowState.

        Args:
            data: JSON string representation of a WorkflowState.

        Returns:
            A reconstructed WorkflowState object.

        Raises:
            DeserializationError: If the JSON is invalid or violates the schema.
        """
        try:
            raw = json.loads(data)
        except json.JSONDecodeError as e:
            raise DeserializationError(
                f"Invalid JSON: {e.msg}",
                failure_type="parse_error",
                offset=e.pos,
            ) from e

        if not isinstance(raw, dict):
            raise DeserializationError(
                "Expected a JSON object at top level",
                failure_type="schema_violation",
                field_path="$",
            )

        # Recursively decode tagged types
        decoded = _recursive_decode(raw)

        # Construct WorkflowState from decoded data
        try:
            return WorkflowState(
                ticket=decoded.get("ticket", {}),
                context=decoded.get("context", {}),
                modified_files=decoded.get("modified_files", []),
                plan=decoded.get("plan", {}),
                logs=decoded.get("logs", []),
                evidence=decoded.get("evidence", []),
                errors=decoded.get("errors", []),
                metrics=decoded.get("metrics", {}),
                metadata=decoded.get("metadata", {}),
            )
        except TypeError as e:
            raise DeserializationError(
                f"Schema violation during WorkflowState construction: {e}",
                failure_type="schema_violation",
                field_path="$",
            ) from e

    def persist(self, state: WorkflowState, filepath: str | Path) -> None:
        """Persist a WorkflowState to a JSON file.

        Writes atomically (temp file + os.replace) under an exclusive file
        lock, so a crash mid-write or a concurrent persist/load never leaves
        or observes a partially-written state file.

        Args:
            state: The WorkflowState to persist.
            filepath: Path to the output file.
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        json_str = self.serialize(state)
        with LedgerLock(lock_path_for(filepath)):
            atomic_write_text(filepath, json_str)

    def load(self, filepath: str | Path) -> WorkflowState:
        """Load a WorkflowState from a JSON file.

        Args:
            filepath: Path to the input file.

        Returns:
            The deserialized WorkflowState.

        Raises:
            FileNotFoundError: If the file does not exist.
            DeserializationError: If the file content is invalid.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"State file not found: {filepath}")
        content = filepath.read_text(encoding="utf-8")
        return self.deserialize(content)

    def _prepare_for_json(self, state: WorkflowState) -> dict[str, Any]:
        """Convert WorkflowState to a dict with type tags for complex types.

        This walks the state fields and wraps datetime, enum, and dataclass
        values with type metadata so deserialization can restore them.
        """
        return {
            "ticket": self._encode_value(state.ticket),
            "context": self._encode_value(state.context),
            "modified_files": self._encode_value(state.modified_files),
            "plan": self._encode_value(state.plan),
            "logs": self._encode_value(state.logs),
            "evidence": self._encode_value(state.evidence),
            "errors": self._encode_value(state.errors),
            "metrics": self._encode_value(state.metrics),
            "metadata": self._encode_value(state.metadata),
        }

    def _encode_value(self, value: Any) -> Any:
        """Recursively encode a value, adding type tags for special types."""
        if isinstance(value, datetime):
            return {"__type__": "datetime", "value": value.isoformat()}
        if isinstance(value, Enum):
            return {
                "__type__": "enum",
                "enum_class": f"{type(value).__module__}.{type(value).__qualname__}",
                "value": value.value,
            }
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                "__type__": "dataclass",
                "class": f"{type(value).__module__}.{type(value).__qualname__}",
                "fields": {
                    field.name: self._encode_value(getattr(value, field.name))
                    for field in dataclasses.fields(value)
                },
            }
        if isinstance(value, dict):
            return {k: self._encode_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._encode_value(item) for item in value]
        return value
