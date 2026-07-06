"""Ledger persistence for audit trail.

The ledger is a JSON file that stores all execution records. It serves as
the single source of truth for offline summary generation and auditing.
"""

import json
import os
from pathlib import Path

from autopilot.domain.entities.ledger_entry import LedgerEntry


class Ledger:
    """Central audit ledger for workflow executions.

    The ledger stores LedgerEntry records in a JSON file. It supports:
    - Idempotent append/replace by run_id
    - Offline summary generation
    - History tracking per ticket
    """

    def __init__(self, ledger_path: str | Path) -> None:
        """Initialize the ledger.

        Args:
            ledger_path: Path to the ledger.json file.
        """
        self._path = Path(ledger_path)

    def load(self) -> list[dict]:
        """Load the ledger data.

        Returns:
            List of ledger entry dictionaries.
        """
        if not self._path.exists():
            return []
        with open(self._path, encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: list[dict]) -> None:
        """Save the ledger data.

        Args:
            data: List of ledger entry dictionaries.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def append(self, entry: LedgerEntry, keep_all: bool = False) -> int:
        """Append or replace a ledger entry.

        By default, replaces the latest entry for the same run_id (idempotent re-runs).
        Use keep_all=True to keep history.

        Args:
            entry: The LedgerEntry to append.
            keep_all: If True, keep all entries for the same run_id.

        Returns:
            Total number of entries in the ledger after the operation.
        """
        # Validate the entry
        warnings = LedgerEntry.validate(entry.to_dict())
        for w in warnings:
            print(f"WARN: {w}")

        data = self.load()

        # Deduplicate by run_id unless keep_all
        if not keep_all:
            data = [r for r in data if r.get("run_id") != entry.run_id]

        data.append(entry.to_dict())
        data.sort(key=lambda r: (r.get("ticket_id", ""), r.get("timestamp", "")))

        self.save(data)
        return len(data)

    def get_by_ticket(self, ticket_id: str) -> list[LedgerEntry]:
        """Get all ledger entries for a ticket.

        Args:
            ticket_id: The ticket ID to search for.

        Returns:
            List of LedgerEntry instances for the ticket.
        """
        data = self.load()
        entries = [
            LedgerEntry.from_dict(r) for r in data
            if r.get("ticket_id") == ticket_id
        ]
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries

    def get_by_run_id(self, run_id: str) -> LedgerEntry | None:
        """Get a ledger entry by run_id.

        Args:
            run_id: The run ID to search for.

        Returns:
            LedgerEntry if found, None otherwise.
        """
        data = self.load()
        for r in data:
            if r.get("run_id") == run_id:
                return LedgerEntry.from_dict(r)
        return None

    def summary(self) -> str:
        """Generate a consolidated Markdown summary of all entries.

        Returns:
            Markdown string with the summary report.
        """
        data = self.load()
        lines: list[str] = []
        w = lines.append

        w("# Autopilot — Resumen de ejecuciones\n")
        w(f"Generado desde `{self._path.name}` · {len(data)} ejecución(es)\n")

        # 1. Status table
        w("## Estado por ejecución\n")
        w("| Run ID | Ticket | Título | Estado | Veredicto | Archivos | Duración |")
        w("|--------|--------|--------|--------|-----------|----------|----------|")
        for r in data:
            v = r.get("verdict", "—")
            dur = f"{r.get('duration_seconds', 0)}s" if r.get("duration_seconds") else "—"
            files = len(r.get("modified_files", []))
            w(f"| `{r.get('run_id', '')[:8]}` | {r.get('ticket_id', '')} | "
              f"{r.get('ticket_title', '')} | {r.get('status', '')} | "
              f"{v} | {files} | {dur} |")
        w("")

        # 2. Aggregated stats
        total = len(data)
        completed = sum(1 for r in data if r.get("status") == "completed")
        failed = sum(1 for r in data if r.get("status") == "failed")
        total_tests = sum(r.get("tests_executed", 0) for r in data)
        total_passed = sum(r.get("tests_passed", 0) for r in data)

        w("## Estadísticas\n")
        w(f"- Total ejecuciones: {total}")
        w(f"- Completadas: {completed}")
        w(f"- Fallidas: {failed}")
        w(f"- Tests ejecutados: {total_tests}")
        w(f"- Tests pasados: {total_passed}")
        if total_tests > 0:
            w(f"- Tasa de éxito: {total_passed / total_tests * 100:.1f}%")
        w("")

        # 3. Per-ticket detail
        w("## Detalle por ejecución\n")
        for r in data:
            v = r.get("verdict", "—")
            dur = f"{r.get('duration_seconds', 0)}s" if r.get("duration_seconds") else "—"
            w(f"### `{r.get('run_id', '')[:8]}` — {r.get('ticket_id', '')} {r.get('ticket_title', '')}\n")
            w(f"- Estado: {r.get('status', '')} · Veredicto: {v} · Duración: {dur}")
            if r.get("modified_files"):
                w(f"- Archivos modificados: {', '.join(r['modified_files'][:5])}")
                if len(r.get("modified_files", [])) > 5:
                    w(f"  - ... y {len(r['modified_files']) - 5} más")
            if r.get("summary"):
                w(f"- Resumen: {r['summary']}")
            w("")

        return "\n".join(lines)

    def size(self) -> int:
        """Get the number of entries in the ledger.

        Returns:
            Number of entries.
        """
        return len(self.load())
