"""Run record store for persisting execution results.

Provides CRUD operations for RunRecord entities, storing them as individual
JSON files in a structured directory layout:
    {workspace}/runs/{run_id}/run-record.json
"""

import json
from pathlib import Path

from autopilot.domain.entities.run_record import RunRecord
from autopilot.infrastructure.persistence.atomic_write import atomic_write_json


class RunRecordStore:
    """Store for persisting and retrieving run records.

    Each run record is stored as a JSON file in its own directory:
        {workspace}/runs/{run_id}/run-record.json

    This isolation ensures concurrent runs cannot race on shared files.
    """

    def __init__(self, workspace: str | Path) -> None:
        """Initialize the run record store.

        Args:
            workspace: Root workspace directory. Run records will be stored
                under {workspace}/runs/.
        """
        self._workspace = Path(workspace)
        self._runs_dir = self._workspace / "runs"

    def save(self, record: RunRecord) -> Path:
        """Save a run record to disk.

        Args:
            record: The RunRecord to save.

        Returns:
            Path to the saved run record file.
        """
        run_dir = self._runs_dir / record.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "run-record.json"

        atomic_write_json(path, record.to_dict())

        return path

    def load(self, run_id: str) -> RunRecord:
        """Load a run record from disk.

        Args:
            run_id: The run ID to load.

        Returns:
            The loaded RunRecord.

        Raises:
            FileNotFoundError: If the run record doesn't exist.
            json.JSONDecodeError: If the JSON is invalid.
        """
        path = self._runs_dir / run_id / "run-record.json"
        if not path.exists():
            raise FileNotFoundError(f"Run record not found: {path}")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        return RunRecord.from_dict(data)

    def exists(self, run_id: str) -> bool:
        """Check if a run record exists.

        Args:
            run_id: The run ID to check.

        Returns:
            True if the run record exists.
        """
        path = self._runs_dir / run_id / "run-record.json"
        return path.exists()

    def list_by_ticket(self, ticket_id: str) -> list[RunRecord]:
        """List all run records for a ticket.

        Args:
            ticket_id: The ticket ID to search for.

        Returns:
            List of RunRecord instances for the ticket, sorted by started_at.
        """
        records = []
        if not self._runs_dir.exists():
            return records

        for run_dir in self._runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            path = run_dir / "run-record.json"
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("ticket_id") == ticket_id:
                    records.append(RunRecord.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue

        records.sort(key=lambda r: r.started_at, reverse=True)
        return records

    def list_all(self, limit: int = 100) -> list[RunRecord]:
        """List all run records.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of RunRecord instances, sorted by started_at descending.
        """
        records = []
        if not self._runs_dir.exists():
            return records

        for run_dir in self._runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            path = run_dir / "run-record.json"
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                records.append(RunRecord.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue

        records.sort(key=lambda r: r.started_at, reverse=True)
        return records[:limit]

    def delete(self, run_id: str) -> bool:
        """Delete a run record.

        Args:
            run_id: The run ID to delete.

        Returns:
            True if the record was deleted, False if it didn't exist.
        """
        run_dir = self._runs_dir / run_id
        if not run_dir.exists():
            return False

        import shutil
        shutil.rmtree(run_dir)
        return True
