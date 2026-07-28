"""Property and unit tests for RunRecordStore atomic writes.

Feature: safe-persistence-and-config-validation
"""

import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.domain.entities.run_record import RunRecord
from autopilot.infrastructure.persistence.run_record_store import RunRecordStore

run_id_strategy = st.from_regex(r"[A-Za-z0-9_-]{1,20}", fullmatch=True)


class TestRunRecordSaveCreatesMissingDirectories:
    """Property 4: Run record save creates missing run directories.

    **Validates: Requirements 2.1**
    """

    @settings(max_examples=100)
    @given(run_id=run_id_strategy)
    def test_save_creates_run_directory_and_runs_dir(self, run_id):
        tmpdir = tempfile.mkdtemp()
        workspace = Path(tmpdir) / "fresh_workspace"
        # `runs/` directory does not yet exist.
        assert not (workspace / "runs").exists()

        store = RunRecordStore(workspace)
        record = RunRecord(run_id=run_id, ticket_id="TEST-1")
        path = store.save(record)

        assert path.exists()
        run_dir = workspace / "runs" / run_id
        assert run_dir.is_dir()
        assert (run_dir / "run-record.json").is_file()

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["run_id"] == run_id


class TestRunRecordStoreAtomicity:
    """Unit tests for RunRecordStore.save() atomicity.

    **Validates: Requirements 2.7**
    """

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = RunRecordStore(self.tmpdir)

    def test_save_produces_valid_parseable_json(self):
        record = RunRecord(run_id="abc123", ticket_id="TEST-123")
        path = self.store.save(record)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["run_id"] == "abc123"
        assert data["ticket_id"] == "TEST-123"

    def test_save_overwrites_previous_content(self):
        record = RunRecord(run_id="abc123", ticket_id="TEST-123", status="running")
        self.store.save(record)

        record.status = "completed"
        path = self.store.save(record)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["status"] == "completed"
