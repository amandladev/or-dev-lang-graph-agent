"""Tests for RunRecord entity and RunRecordStore."""

import json
import os
import tempfile

import pytest

from autopilot.domain.entities.run_record import RunRecord
from autopilot.infrastructure.persistence.run_record_store import RunRecordStore


class TestRunRecord:
    """Tests for RunRecord entity."""

    def test_default_values(self):
        record = RunRecord()
        assert record.run_id  # auto-generated
        assert record.ticket_id == ""
        assert record.status == "running"
        assert record.verdict is None
        assert record.started_at  # auto-generated

    def test_mark_completed(self):
        record = RunRecord()
        record.mark_completed("PASS")
        assert record.status == "completed"
        assert record.verdict == "PASS"
        assert record.finished_at is not None
        assert record.duration_seconds is not None

    def test_mark_failed(self):
        record = RunRecord()
        record.mark_failed("Something went wrong")
        assert record.status == "failed"
        assert len(record.errors) == 1
        assert record.errors[0]["description"] == "Something went wrong"

    def test_mark_cancelled(self):
        record = RunRecord()
        record.mark_cancelled()
        assert record.status == "cancelled"
        assert record.finished_at is not None

    def test_add_log(self):
        record = RunRecord()
        record.add_log({"agent": "planner", "status": "success"})
        assert len(record.logs) == 1

    def test_add_error(self):
        record = RunRecord()
        record.add_error({"type": "test_failure", "description": "error"})
        assert len(record.errors) == 1

    def test_add_evidence(self):
        record = RunRecord()
        record.add_evidence({"type": "screenshot", "path": "/tmp/test.png"})
        assert len(record.evidence) == 1

    def test_update_test_counts(self):
        record = RunRecord()
        record.update_test_counts(executed=10, passed=8, failed=2)
        assert record.tests_executed == 10
        assert record.tests_passed == 8
        assert record.tests_failed == 2

    def test_to_dict(self):
        record = RunRecord(ticket_id="TEST-123", mode="dry-run")
        data = record.to_dict()
        assert data["ticket_id"] == "TEST-123"
        assert data["mode"] == "dry-run"
        assert "run_id" in data

    def test_from_dict(self):
        data = {
            "run_id": "abc123",
            "ticket_id": "TEST-123",
            "status": "completed",
            "verdict": "PASS",
        }
        record = RunRecord.from_dict(data)
        assert record.run_id == "abc123"
        assert record.ticket_id == "TEST-123"
        assert record.status == "completed"

    def test_validate_valid(self):
        data = {
            "run_id": "abc123",
            "ticket_id": "TEST-123",
            "started_at": "2024-01-01T00:00:00Z",
            "status": "completed",
        }
        warnings = RunRecord.validate(data)
        assert warnings == []

    def test_validate_missing_fields(self):
        data = {"status": "completed"}
        warnings = RunRecord.validate(data)
        assert len(warnings) == 3  # missing run_id, ticket_id, started_at

    def test_validate_invalid_status(self):
        data = {
            "run_id": "abc123",
            "ticket_id": "TEST-123",
            "started_at": "2024-01-01T00:00:00Z",
            "status": "invalid",
        }
        warnings = RunRecord.validate(data)
        assert any("Invalid status" in w for w in warnings)


class TestRunRecordStore:
    """Tests for RunRecordStore persistence."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = RunRecordStore(self.tmpdir)

    def test_save_and_load(self):
        record = RunRecord(ticket_id="TEST-123")
        self.store.save(record)

        loaded = self.store.load(record.run_id)
        assert loaded.ticket_id == "TEST-123"
        assert loaded.run_id == record.run_id

    def test_exists(self):
        record = RunRecord(ticket_id="TEST-123")
        assert not self.store.exists(record.run_id)

        self.store.save(record)
        assert self.store.exists(record.run_id)

    def test_list_by_ticket(self):
        r1 = RunRecord(ticket_id="TEST-123")
        r2 = RunRecord(ticket_id="TEST-123")
        r3 = RunRecord(ticket_id="TEST-456")

        self.store.save(r1)
        self.store.save(r2)
        self.store.save(r3)

        results = self.store.list_by_ticket("TEST-123")
        assert len(results) == 2

    def test_list_all(self):
        for i in range(5):
            self.store.save(RunRecord(ticket_id=f"TEST-{i}"))

        results = self.store.list_all(limit=3)
        assert len(results) == 3

    def test_delete(self):
        record = RunRecord(ticket_id="TEST-123")
        self.store.save(record)
        assert self.store.exists(record.run_id)

        self.store.delete(record.run_id)
        assert not self.store.exists(record.run_id)

    def test_load_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            self.store.load("nonexistent")
