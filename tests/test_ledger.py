"""Tests for LedgerEntry entity and Ledger persistence."""

import json
import os
import tempfile

from autopilot.domain.entities.ledger_entry import LedgerEntry
from autopilot.domain.entities.run_record import RunRecord
from autopilot.infrastructure.persistence.ledger import Ledger


class TestLedgerEntry:
    """Tests for LedgerEntry entity."""

    def test_default_values(self):
        entry = LedgerEntry()
        assert entry.run_id == ""
        assert entry.ticket_id == ""
        assert entry.status == "completed"
        assert entry.verdict is None

    def test_to_dict(self):
        entry = LedgerEntry(run_id="abc123", ticket_id="TEST-123", verdict="PASS")
        data = entry.to_dict()
        assert data["run_id"] == "abc123"
        assert data["ticket_id"] == "TEST-123"
        assert data["verdict"] == "PASS"

    def test_from_dict(self):
        data = {
            "run_id": "abc123",
            "ticket_id": "TEST-123",
            "status": "completed",
            "verdict": "PASS",
        }
        entry = LedgerEntry.from_dict(data)
        assert entry.run_id == "abc123"
        assert entry.ticket_id == "TEST-123"

    def test_from_run_record(self):
        record = RunRecord(
            run_id="abc123",
            ticket_id="TEST-123",
            ticket_title="Test Ticket",
            status="completed",
            verdict="PASS",
            tests_executed=10,
            tests_passed=10,
        )
        entry = LedgerEntry.from_run_record(record)
        assert entry.run_id == "abc123"
        assert entry.ticket_id == "TEST-123"
        assert entry.verdict == "PASS"
        assert entry.tests_executed == 10
        assert entry.tests_passed == 10
        assert "PASS" in entry.summary

    def test_validate_valid(self):
        data = {
            "run_id": "abc123",
            "ticket_id": "TEST-123",
            "timestamp": "2024-01-01T00:00:00Z",
            "status": "completed",
        }
        warnings = LedgerEntry.validate(data)
        assert warnings == []

    def test_validate_missing_fields(self):
        data = {"status": "completed"}
        warnings = LedgerEntry.validate(data)
        assert len(warnings) == 3  # missing run_id, ticket_id, timestamp


class TestLedger:
    """Tests for Ledger persistence."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = os.path.join(self.tmpdir, "ledger.json")
        self.ledger = Ledger(self.ledger_path)

    def test_load_empty(self):
        data = self.ledger.load()
        assert data == []

    def test_append_and_load(self):
        entry = LedgerEntry(run_id="abc123", ticket_id="TEST-123", verdict="PASS")
        count = self.ledger.append(entry)
        assert count == 1

        data = self.ledger.load()
        assert len(data) == 1
        assert data[0]["run_id"] == "abc123"

    def test_append_idempotent(self):
        entry1 = LedgerEntry(run_id="abc123", ticket_id="TEST-123", verdict="PASS")
        entry2 = LedgerEntry(run_id="abc123", ticket_id="TEST-123", verdict="FAIL")

        self.ledger.append(entry1)
        self.ledger.append(entry2)  # Should replace

        data = self.ledger.load()
        assert len(data) == 1
        assert data[0]["verdict"] == "FAIL"

    def test_append_keep_all(self):
        entry1 = LedgerEntry(run_id="abc123", ticket_id="TEST-123", verdict="PASS")
        entry2 = LedgerEntry(run_id="abc123", ticket_id="TEST-123", verdict="FAIL")

        self.ledger.append(entry1, keep_all=True)
        self.ledger.append(entry2, keep_all=True)

        data = self.ledger.load()
        assert len(data) == 2

    def test_get_by_ticket(self):
        e1 = LedgerEntry(run_id="abc", ticket_id="TEST-123", verdict="PASS")
        e2 = LedgerEntry(run_id="def", ticket_id="TEST-123", verdict="FAIL")
        e3 = LedgerEntry(run_id="ghi", ticket_id="TEST-456", verdict="PASS")

        self.ledger.append(e1)
        self.ledger.append(e2)
        self.ledger.append(e3)

        results = self.ledger.get_by_ticket("TEST-123")
        assert len(results) == 2

    def test_get_by_run_id(self):
        entry = LedgerEntry(run_id="abc123", ticket_id="TEST-123")
        self.ledger.append(entry)

        found = self.ledger.get_by_run_id("abc123")
        assert found is not None
        assert found.run_id == "abc123"

        not_found = self.ledger.get_by_run_id("nonexistent")
        assert not_found is None

    def test_summary(self):
        entry = LedgerEntry(
            run_id="abc123",
            ticket_id="TEST-123",
            verdict="PASS",
            tests_executed=10,
            tests_passed=10,
        )
        self.ledger.append(entry)

        summary = self.ledger.summary()
        assert "TEST-123" in summary
        assert "PASS" in summary

    def test_size(self):
        assert self.ledger.size() == 0

        self.ledger.append(LedgerEntry(run_id="abc123", ticket_id="TEST-123"))
        assert self.ledger.size() == 1

    def test_save_produces_valid_parseable_json_equal_to_data(self):
        """**Validates: Requirements 1.6**

        Ledger.save() produces valid JSON, parseable without error, and
        equal to the data most recently saved.
        """
        data = [
            {"run_id": "abc123", "ticket_id": "TEST-123", "status": "completed"},
            {"run_id": "def456", "ticket_id": "TEST-456", "status": "failed"},
        ]
        self.ledger.save(data)

        with open(self.ledger_path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded == data

    def test_save_overwrites_previous_content_atomically(self):
        """**Validates: Requirements 1.6**

        A second save() call replaces the previous content with new content.
        """
        self.ledger.save([{"run_id": "one"}])
        self.ledger.save([{"run_id": "two"}])

        with open(self.ledger_path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded == [{"run_id": "two"}]
