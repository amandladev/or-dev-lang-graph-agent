"""Unit tests for JSONSerializer.

Tests serialization/deserialization of WorkflowState, error reporting,
and file I/O operations.

Validates: Requirements 13.1, 13.2, 13.3, 13.5, 13.6
"""

import tempfile
import os
from datetime import datetime
from pathlib import Path

import pytest

from autopilot.infrastructure.adapters.json_serializer import (
    DeserializationError,
    JSONSerializer,
)
from autopilot.domain.entities.workflow_state import WorkflowState
from autopilot.domain.value_objects.log_entry import LogEntry, StepStatus
from autopilot.domain.value_objects.evidence import EvidenceItem
from autopilot.domain.value_objects.error_record import ErrorRecord, ErrorType
from autopilot.domain.interfaces.serializer import SerializerInterface


class TestJSONSerializerProtocol:
    """Verify JSONSerializer satisfies the SerializerInterface protocol."""

    def test_implements_serializer_interface(self):
        serializer = JSONSerializer()
        assert isinstance(serializer, SerializerInterface)


class TestSerializeDeserializeRoundTrip:
    """Verify round-trip serialization for WorkflowState with complex nested types."""

    def test_empty_state_round_trip(self):
        state = WorkflowState()
        serializer = JSONSerializer()
        json_str = serializer.serialize(state)
        restored = serializer.deserialize(json_str)
        assert restored == state

    def test_state_with_log_entries(self):
        state = WorkflowState(
            logs=[
                LogEntry(
                    agent_name="Planner",
                    start_time=datetime(2024, 1, 15, 10, 0, 0),
                    end_time=datetime(2024, 1, 15, 10, 0, 5),
                    elapsed_ms=5000,
                    input_data={"ticket_id": "T-123"},
                    output_data={"plan": {"steps": []}},
                    status=StepStatus.SUCCESS,
                ),
                LogEntry(
                    agent_name="Tester",
                    start_time=datetime(2024, 1, 15, 10, 1, 0),
                    end_time=datetime(2024, 1, 15, 10, 1, 30),
                    elapsed_ms=30000,
                    input_data={},
                    output_data={},
                    status=StepStatus.FAILED,
                ),
            ]
        )
        serializer = JSONSerializer()
        restored = serializer.deserialize(serializer.serialize(state))
        assert restored.logs == state.logs
        assert restored.logs[0].status == StepStatus.SUCCESS
        assert restored.logs[1].status == StepStatus.FAILED

    def test_state_with_evidence_items(self):
        state = WorkflowState(
            evidence=[
                EvidenceItem(type="test_result", description="All pass", path="/tmp/results.json", data={"passed": 10}),
                EvidenceItem(type="screenshot", description="Home page", path=None, data=None),
            ]
        )
        serializer = JSONSerializer()
        restored = serializer.deserialize(serializer.serialize(state))
        assert restored.evidence == state.evidence

    def test_state_with_error_records(self):
        state = WorkflowState(
            errors=[
                ErrorRecord(
                    error_type=ErrorType.RETRYABLE,
                    description="Connection timeout",
                    agent_name="Publisher",
                    attempt_count=3,
                    exception_class="TimeoutError",
                ),
                ErrorRecord(
                    error_type=ErrorType.NON_RETRYABLE,
                    description="Bad credentials",
                    agent_name="ContextBuilder",
                    attempt_count=0,
                    exception_class="AuthenticationError",
                ),
            ]
        )
        serializer = JSONSerializer()
        restored = serializer.deserialize(serializer.serialize(state))
        assert restored.errors == state.errors

    def test_full_complex_state_round_trip(self):
        state = WorkflowState(
            ticket={"id": "PROJ-999", "title": "Complex feature", "labels": ["urgent"]},
            context={"related": [{"file": "main.py", "lines": [1, 50]}]},
            modified_files=["src/app.py", "tests/test_app.py"],
            plan={"steps": [{"agent": "CodeExecutor", "inputs": {"files": []}}]},
            logs=[
                LogEntry(
                    agent_name="ContextBuilder",
                    start_time=datetime(2024, 6, 1, 8, 0, 0),
                    end_time=datetime(2024, 6, 1, 8, 0, 2),
                    elapsed_ms=2000,
                    input_data={"ticket_id": "PROJ-999"},
                    output_data={"context": {}},
                    status=StepStatus.SUCCESS,
                )
            ],
            evidence=[EvidenceItem(type="log_file", description="Build log", path="/tmp/build.log")],
            errors=[],
            metrics={"total_duration_ms": 15000, "steps_executed": 3},
            metadata={"version": "1.0", "run_id": "abc-123"},
        )
        serializer = JSONSerializer()
        restored = serializer.deserialize(serializer.serialize(state))
        assert restored == state


class TestDeserializationErrors:
    """Verify error reporting with failure type and field path/offset."""

    def test_invalid_json_reports_parse_error_with_offset(self):
        serializer = JSONSerializer()
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize("{not valid json}")
        err = exc_info.value
        assert err.failure_type == "parse_error"
        assert err.offset is not None
        assert err.offset >= 0

    def test_non_object_json_reports_schema_violation(self):
        serializer = JSONSerializer()
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize('"just a string"')
        err = exc_info.value
        assert err.failure_type == "schema_violation"
        assert err.field_path == "$"

    def test_array_json_reports_schema_violation(self):
        serializer = JSONSerializer()
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize("[1, 2, 3]")
        err = exc_info.value
        assert err.failure_type == "schema_violation"

    def test_invalid_enum_value_reports_field_path(self):
        serializer = JSONSerializer()
        # Craft JSON with an invalid enum value
        bad_json = '''{
            "ticket": {},
            "errors": [
                {
                    "__type__": "dataclass",
                    "class": "autopilot.domain.value_objects.error_record.ErrorRecord",
                    "fields": {
                        "error_type": {
                            "__type__": "enum",
                            "enum_class": "autopilot.domain.value_objects.error_record.ErrorType",
                            "value": "INVALID_VALUE"
                        },
                        "description": "test",
                        "agent_name": "test",
                        "attempt_count": 0,
                        "exception_class": ""
                    }
                }
            ]
        }'''
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(bad_json)
        err = exc_info.value
        assert err.failure_type == "schema_violation"
        assert "error_type" in (err.field_path or "")

    def test_unknown_dataclass_reports_schema_violation(self):
        serializer = JSONSerializer()
        bad_json = '''{
            "logs": [
                {
                    "__type__": "dataclass",
                    "class": "nonexistent.module.FakeClass",
                    "fields": {}
                }
            ]
        }'''
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(bad_json)
        err = exc_info.value
        assert err.failure_type == "schema_violation"
        assert "nonexistent" in str(err)


class TestFileIO:
    """Verify persist and load file operations."""

    def test_persist_creates_file_and_subdirectories(self):
        state = WorkflowState(ticket={"id": "FILE-TEST"})
        serializer = JSONSerializer()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "deep", "nested", "state.json")
            serializer.persist(state, filepath)
            assert os.path.exists(filepath)

    def test_load_restores_persisted_state(self):
        state = WorkflowState(
            ticket={"id": "LOAD-TEST"},
            modified_files=["a.py", "b.py"],
            metadata={"key": "value"},
        )
        serializer = JSONSerializer()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "state.json")
            serializer.persist(state, filepath)
            loaded = serializer.load(filepath)
            assert loaded == state

    def test_load_nonexistent_file_raises_file_not_found(self):
        serializer = JSONSerializer()
        with pytest.raises(FileNotFoundError):
            serializer.load("/tmp/nonexistent_serializer_test_xyz.json")

    def test_load_invalid_json_file_raises_deserialization_error(self):
        serializer = JSONSerializer()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "bad.json")
            Path(filepath).write_text("not json at all", encoding="utf-8")
            with pytest.raises(DeserializationError) as exc_info:
                serializer.load(filepath)
            assert exc_info.value.failure_type == "parse_error"

    def test_persist_with_path_object(self):
        state = WorkflowState(metrics={"elapsed": 500})
        serializer = JSONSerializer()

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "state.json"
            serializer.persist(state, filepath)
            loaded = serializer.load(filepath)
            assert loaded == state
