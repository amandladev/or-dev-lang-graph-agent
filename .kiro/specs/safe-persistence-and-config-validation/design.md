# Design Document

## Overview

This feature hardens two areas of Autopilot's persistence and CLI layers:

1. **Crash-safe writes.** `Ledger.save()` and `RunRecordStore.save()` currently write JSON directly to their destination files with `open(path, "w")` + `json.dump()`. This leaves a window where a crash or interruption can truncate or corrupt the destination file. Both classes will be migrated to a shared **atomic write helper** that writes to a temp file in the same directory, flushes and closes it, then uses `os.replace()` to swap it into place.
2. **Concurrency-safe ledger appends.** `Ledger.append()` performs a load → modify → save cycle with no coordination across processes. Two concurrent `autopilot` invocations can interleave their read-modify-write cycles and lose an entry. A new **`LedgerLock`** context manager (stdlib-only, `fcntl` on POSIX / `msvcrt` on Windows) will serialize the append cycle across processes using a lock file colocated with `ledger.json`.
3. **Consistent config sanity checking.** Only the `work` command currently validates configuration before use, via the relatively heavyweight `validate_environment` (checks `opencode`, `git`, Jira credentials, etc.). A new, lightweight, stdlib-only **`config_sanity_validator`** will check only `workspace_location` and `vault_location`, and will be invoked by `config`, `ledger`, `resume`, and `work` immediately after `create_application()`, before any other use of the resulting `Config`.

None of these changes alter the public shape of `LedgerEntry`, `RunRecord`, or `Config`; they change *how* those objects are persisted and *when* configuration is checked.

## Architecture

```
autopilot/infrastructure/persistence/
├── atomic_write.py        (NEW) shared atomic JSON write helper
├── file_lock.py           (NEW) cross-platform advisory file lock (LedgerLock)
├── ledger.py              (MODIFIED) uses atomic_write.py + file_lock.py
└── run_record_store.py    (MODIFIED) uses atomic_write.py

autopilot/infrastructure/
└── validators.py          (MODIFIED) adds config_sanity_validator()

autopilot/cli/
└── commands.py            (MODIFIED) wires config_sanity_validator() into
                            config, ledger, resume, work commands
```

Dependency direction is preserved: the two new persistence-layer modules sit alongside `ledger.py` and `run_record_store.py` inside `infrastructure/persistence/`, and `validators.py` remains a standalone infrastructure module with no new external dependencies (stdlib only, matching the project's existing convention of not introducing third-party locking libraries).

## Components and Interfaces

### 1. `atomic_write.py` — shared atomic write helper

```python
"""Atomic, crash-safe JSON file writes.

Shared by Ledger and RunRecordStore so that a save operation never leaves
the destination file in a partially-written state.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Write `data` as JSON to `path` atomically.

    Writes the serialized content to a temporary file in the same directory
    as `path`, flushes and closes it, then uses os.replace() to move it into
    place. If serialization or the write fails, the temporary file is removed
    and any pre-existing file at `path` is left untouched. If os.replace()
    itself fails, both the temporary file and any pre-existing file at `path`
    are left untouched.

    Args:
        path: Destination file path.
        data: JSON-serializable data to write.
        indent: Indentation level passed to json.dump.

    Raises:
        TypeError: If `data` is not JSON-serializable.
        OSError: If a filesystem error occurs while writing or replacing.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        _remove_if_exists(tmp_path)
        raise

    os.replace(tmp_path, destination)
```

- `tempfile.mkstemp(dir=destination.parent, ...)` guarantees the temp file is created in the same directory (required for `os.replace()` to be atomic on POSIX and required by Requirement 1.1/2.2) and guarantees a unique, non-colliding name across concurrent callers (the OS-level `mkstemp` uses `O_EXCL` semantics).
- The `prefix=f".{destination.name}."` makes the temp file trivially distinguishable from the destination file (e.g. `.ledger.json.a1b2c3.tmp` vs `ledger.json`).
- `json.dump` errors (e.g. non-serializable data) and any I/O error while writing raise before `os.replace()` is reached; the `except` block removes the temp file and re-raises, satisfying Requirement 1.4/2.5 — the pre-existing destination file was never touched.
- If `os.replace()` itself raises (e.g. cross-device rename on an unusual mount, or a permissions error), the exception propagates without any cleanup — the temp file and any pre-existing destination remain exactly as they were, satisfying Requirement 1.5/2.6.
- `_remove_if_exists` swallows `FileNotFoundError` only, so a double-failure (write fails and temp file cleanup fails for an unrelated reason) still surfaces the *original* error rather than masking it.

```python
def _remove_if_exists(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
```

### 2. `file_lock.py` — cross-platform advisory lock

```python
"""Cross-platform advisory file lock used to serialize Ledger appends
across processes.

Uses only Python standard library facilities: fcntl.flock on POSIX,
msvcrt.locking on Windows. No third-party locking dependency is introduced.
"""

from pathlib import Path
from types import TracebackType

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


class LedgerLock:
    """Advisory, blocking, exclusive lock held for the duration of a
    Ledger load-modify-write append cycle."""

    def __init__(self, lock_path: str | Path) -> None:
        self._lock_path = Path(lock_path)
        self._fh = None

    def __enter__(self) -> "LedgerLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._lock_path, "a+b")
        try:
            if fcntl is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                raise OSError(
                    "No supported file locking mechanism (fcntl/msvcrt) "
                    "available on this platform"
                )
        except Exception:
            self._fh.close()
            self._fh = None
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            if self._fh is not None:
                if fcntl is not None:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
        return False


def lock_path_for(target_path: str | Path) -> Path:
    """Deterministically derive a lock file path from a target file path.

    Two calls with the same `target_path` always return the same lock path.
    """
    return Path(str(target_path) + ".lock")
```

- `LedgerLock` is a context manager so it composes naturally with a `with` block wrapping the load-modify-save cycle, and guarantees release via `__exit__`/`finally` even when an exception propagates out of the `with` block (Requirement 3.5).
- If lock acquisition itself raises (unsupported platform, permissions failure), `__enter__` closes the file handle it opened and re-raises before entering the `with` block body, so no load/modify/save logic ever runs (Requirement 3.6).
- `lock_path_for()` is a pure function of the path string, so `Ledger("workspace/ledger.json")` and a second `Ledger("workspace/ledger.json")` always compute the identical lock path `workspace/ledger.json.lock` (Requirement 3.7).
- The lock is process-exclusive advisory locking (`LOCK_EX` / `LK_LOCK`), which blocks the calling thread indefinitely until acquired, matching Requirement 3.1 (no timeout, no polling).

### 3. `ledger.py` — updated `Ledger`

```python
from autopilot.infrastructure.persistence.atomic_write import atomic_write_json
from autopilot.infrastructure.persistence.file_lock import LedgerLock, lock_path_for


class Ledger:
    def __init__(self, ledger_path: str | Path) -> None:
        self._path = Path(ledger_path)
        self._lock_path = lock_path_for(self._path)

    def load(self) -> list[dict]:
        ...  # unchanged

    def save(self, data: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path, data)

    def append(self, entry: LedgerEntry, keep_all: bool = False) -> int:
        warnings = LedgerEntry.validate(entry.to_dict())
        for w in warnings:
            print(f"WARN: {w}")

        with LedgerLock(self._lock_path):
            data = self.load()
            if not keep_all:
                data = [r for r in data if r.get("run_id") != entry.run_id]
            data.append(entry.to_dict())
            data.sort(key=lambda r: (r.get("ticket_id", ""), r.get("timestamp", "")))
            self.save(data)
            count = len(data)

        return count
```

`save()` becomes a thin atomic-write call; `append()` wraps the existing load-modify-save body in `with LedgerLock(...)`. Because `LedgerLock.__exit__` always runs (even on exception), the lock is released whether `append()` succeeds or a step inside the `with` block raises — satisfying Requirement 3.2/3.4/3.5 without any explicit `try/finally` in `Ledger` itself.

### 4. `run_record_store.py` — updated `RunRecordStore`

```python
from autopilot.infrastructure.persistence.atomic_write import atomic_write_json


class RunRecordStore:
    def save(self, record: RunRecord) -> Path:
        run_dir = self._runs_dir / record.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "run-record.json"

        atomic_write_json(path, record.to_dict())

        return path
```

`run_dir.mkdir(parents=True, exist_ok=True)` still runs before the atomic write (Requirement 2.1); `atomic_write_json` itself also calls `mkdir` defensively, which is a no-op here since the directory already exists.

### 5. `validators.py` — `config_sanity_validator`

```python
import os
from pathlib import Path


def config_sanity_validator(config) -> ValidationResult:
    """Lightweight, fast sanity check of core configuration values.

    Distinct from validate_environment: checks only that workspace_location
    and vault_location are non-blank, and that workspace_location is
    creatable. Does not check opencode/git/Jira availability and does not
    create any directories as a side effect.

    Args:
        config: The loaded Config object.

    Returns:
        ValidationResult with errors and warnings.
    """
    result = ValidationResult()

    workspace = config.workspace_location
    vault = config.vault_location

    if not workspace or not workspace.strip():
        result.add_error("workspace_location must not be empty")

    if not vault or not vault.strip():
        result.add_error("vault_location must not be empty")

    if workspace and workspace.strip():
        creatable, reason = _is_creatable_path(workspace)
        if not creatable:
            result.add_error(f"workspace_location is not creatable: {reason}")

    return result


def _is_creatable_path(path_str: str) -> tuple[bool, str]:
    """Check whether a path either already exists as a directory, or has a
    writable existing ancestor, without creating anything.

    Returns:
        (True, "") if creatable, (False, reason) otherwise.
    """
    path = Path(path_str).expanduser()

    try:
        if path.exists():
            if path.is_dir():
                return True, ""
            return False, f"'{path}' already exists and is not a directory"

        ancestor = path.parent
        while not ancestor.exists():
            parent = ancestor.parent
            if parent == ancestor:
                return False, f"no existing ancestor directory found above '{path}'"
            ancestor = parent

        if not ancestor.is_dir():
            return False, f"ancestor '{ancestor}' exists but is not a directory"

        if not os.access(ancestor, os.W_OK):
            return False, f"ancestor directory '{ancestor}' is not writable"

        return True, ""
    except OSError as exc:
        return False, f"filesystem error while checking '{path}': {exc}"
```

- `_is_creatable_path` never calls `mkdir`; it only calls `exists()`, `is_dir()`, and `os.access()`, so it has no side effects (Requirement 4.6).
- Walking `path.parent` upward until an existing ancestor is found, then checking that ancestor's writability, directly implements Requirement 4.4/4.5's "nearest existing ancestor" rule.
- `config_sanity_validator` never imports or calls `validate_environment`, `shutil.which`, or reads Jira env vars, keeping it independent per Requirement 4.8.
- `ValidationResult.valid` is already `True` by default and flipped to `False` by `add_error`, so Requirement 4.7 ("valid is false iff errors were added") falls out of the existing `ValidationResult` dataclass behavior with no new logic needed.

### 6. `cli/commands.py` — wiring

Each of `config`, `ledger`, `resume`, and `work` gets the same three-line insertion immediately after `create_application()` and before any other Config-reading operation:

```python
from autopilot.infrastructure.validators import config_sanity_validator
...
app = create_application(config_path)

sanity = config_sanity_validator(app.config)
if _print_validation(sanity):
    sys.exit(1)
```

For `work`, this insertion goes *before* the existing `skip_validation` branch that calls `validate_environment`, and runs unconditionally regardless of `--skip-validation`:

```python
app = create_application(config_path)

sanity = config_sanity_validator(app.config)
if _print_validation(sanity):
    sys.exit(1)

if not skip_validation:
    click.secho("Validating environment...", fg="white", dim=True)
    validation = validate_environment(app.config, ticket_id)
    if _print_validation(validation):
        sys.exit(1)
    ...
```

`_print_validation` is reused unchanged — it already prints warnings, prints errors, and returns `True` (signal to abort) exactly when `result.errors` is non-empty, which matches Requirement 5.5/5.6 without modification.

## Data Models

No new persistent data models are introduced. `LedgerEntry`, `RunRecord`, and `Config` are unchanged. The only new runtime types are:

- `ValidationResult` (existing, reused as-is) — returned by `config_sanity_validator`.
- No new dataclasses for the atomic write helper or `LedgerLock`; they are pure functions / a small stateful context manager, not domain entities.

## Error Handling

| Failure point | Behavior |
|---|---|
| `json.dump` fails inside `atomic_write_json` (unserializable data) | Temp file removed, destination untouched, `TypeError`/`ValueError` propagated |
| I/O error while writing temp file | Temp file removed, destination untouched, `OSError` propagated |
| `os.replace()` fails | Temp file *and* destination left untouched, `OSError` propagated |
| `LedgerLock.__enter__` fails (unsupported platform, permissions) | File handle closed, no load/modify/save performed, `OSError` propagated |
| Exception during `Ledger.append()`'s load/modify/save body | Lock released via `__exit__`, original exception propagated unchanged |
| `config_sanity_validator` finds blank/non-creatable paths | Errors appended to `ValidationResult`, no exception raised — surfaced by the CLI via `_print_validation` + `sys.exit(1)` |
| Filesystem error while probing ancestor writability (e.g. race, permission denied) | Caught as `OSError` inside `_is_creatable_path`, converted into a validator error rather than propagating |

The CLI layer never needs new `try/except` blocks for the sanity check itself: `config_sanity_validator` is designed to never raise for ordinary bad-config input, only to return errors in the `ValidationResult`. Unexpected exceptions (e.g. a `Config` object missing an attribute) would still surface through the commands' existing outer `except Exception as exc` handlers.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Successful atomic write round-trips arbitrary JSON-serializable data

For any JSON-serializable data (list of dicts, or a RunRecord's dict representation) and any destination path, calling the atomic write helper (directly, or via `Ledger.save()` / `RunRecordStore.save()`) and then reading back the destination file SHALL produce valid JSON equal to the data that was written.

**Validates: Requirements 1.6, 2.7**

### Property 2: Write-time failure leaves the destination untouched and cleans up the temp file

For any pre-existing destination file content and any data whose write to the temporary file fails (unserializable data, or an injected I/O error before the file is closed), calling the atomic write helper SHALL propagate the error, SHALL leave the pre-existing destination file's content byte-for-byte unchanged, and SHALL leave no temporary file behind in the destination directory afterward.

**Validates: Requirements 1.4, 2.5**

### Property 3: Replace-time failure leaves both the temp file and destination untouched

For any pre-existing destination file content and any injected failure of the `os.replace()` step, calling the atomic write helper SHALL propagate the error, SHALL leave the pre-existing destination file's content byte-for-byte unchanged, and SHALL leave the temporary file present and unmodified in the destination directory afterward.

**Validates: Requirements 1.5, 2.6**

### Property 4: Run record save creates missing run directories

For any run_id (including one whose run directory, and the `runs/` directory itself, do not yet exist), calling `RunRecordStore.save()` SHALL result in the run directory existing and containing a valid `run-record.json` file afterward.

**Validates: Requirements 2.1**

### Property 5: Concurrent ledger appends never lose entries

For any set of N distinct `LedgerEntry` values with distinct `run_id`s, appending all N of them to the same ledger path — whether sequentially or with their load-modify-save cycles forced to interleave via lock contention — SHALL result in a final ledger that contains all N entries, with no entry silently dropped or overwritten by another.

**Validates: Requirements 3.1, 3.2**

### Property 6: Lock is released after a successful append

For any sequence of successful `Ledger.append()` calls against the same ledger path, each call SHALL be able to acquire the `Ledger_Lock` without indefinite blocking, demonstrating that the previous call released the lock upon normal completion.

**Validates: Requirements 3.4**

### Property 7: Lock is released after a failed append

For any injected exception raised during the load, modify, or save step of `Ledger.append()`'s critical section, the exception SHALL propagate to the caller, and a subsequent attempt to acquire the same `Ledger_Lock` (e.g. a non-blocking probe) SHALL succeed immediately, demonstrating the lock was released despite the failure.

**Validates: Requirements 3.5**

### Property 8: Lock acquisition/release OS errors prevent any ledger mutation

For any pre-existing ledger file content, if acquiring or releasing the `Ledger_Lock` raises an OS-level error (simulated via an unsupported-locking-mechanism condition or a forced `OSError`), `Ledger.append()` SHALL propagate that error and the ledger file's content SHALL remain byte-for-byte unchanged, demonstrating that no load/modify/save step executed.

**Validates: Requirements 3.6**

### Property 9: Lock path is a deterministic function of the ledger path

For any ledger file path string, two `Ledger` instances constructed with that same path SHALL compute identical lock file paths, and constructing a `Ledger` with a different path SHALL compute a lock file path that differs whenever the ledger paths differ.

**Validates: Requirements 3.7**

### Property 10: Blank location fields are rejected and validity reflects error state

For any string composed entirely of whitespace (including the empty string) supplied as `workspace_location` or `vault_location`, `config_sanity_validator` SHALL add an error mentioning the corresponding field, and for any combination of field values, the returned `ValidationResult.valid` SHALL be `false` if and only if at least one error was added.

**Validates: Requirements 4.2, 4.3, 4.7**

### Property 11: Workspace creatability check matches the nearest-existing-ancestor model, without side effects

For any non-empty `workspace_location` path under a temporary directory tree — whether the path already exists as a directory, is occupied by a plain file, has a writable nearest existing ancestor, or has a non-writable nearest existing ancestor — `config_sanity_validator` SHALL classify the path as creatable if and only if an independently computed reference check (path exists as a directory, OR its nearest existing ancestor exists, is a directory, and is writable) says it is creatable, SHALL add a descriptive error when it is not creatable, and SHALL NOT cause the path to exist on disk after validation completes.

**Validates: Requirements 4.4, 4.5, 4.6**

## Testing Strategy

Tests follow the existing project conventions in `tests/test_ledger.py` (class-based `unittest`-style grouping with `setup_method` + `tempfile.mkdtemp()`) and `tests/test_config_validation.py` (Hypothesis property tests with `@settings(max_examples=100)` and `@given(...)`, docstrings citing the validated requirement numbers).

### Property-based tests (Hypothesis, ≥100 examples each)

New file `tests/test_atomic_write.py`:
- Property 1 (round trip): generate arbitrary JSON-serializable structures (`st.recursive` over dicts/lists/text/numbers/booleans/None) and arbitrary filenames; write via `atomic_write_json`, read back, assert equality.
- Property 2 (write failure cleanup): generate arbitrary pre-existing destination bytes and arbitrary data; monkeypatch `json.dump` to raise partway through; assert destination unchanged and no `*.tmp` files remain in the directory.
- Property 3 (replace failure): generate arbitrary pre-existing destination bytes; monkeypatch `os.replace` to raise; assert destination unchanged and exactly one temp file remains.

New file `tests/test_run_record_store.py` (or extend if it exists):
- Property 4 (directory creation): generate random run_id strings (safe path segments) where the `runs/` dir does not yet exist; assert `save()` creates it and a readable `run-record.json`.
- Reuse Property 1/2/3 at the `RunRecordStore.save()` call site for direct requirement traceability to 2.5/2.6/2.7.

New file `tests/test_ledger_lock.py`:
- Property 5 (no lost updates): use a `ThreadPoolExecutor` to fire N `Ledger.append()` calls concurrently against the same ledger path with distinct `run_id`s; assert the final ledger has exactly N entries covering all run_ids.
- Property 6 (release on success): repeated sequential `append()` calls each complete within a short timeout (guarding against deadlock).
- Property 7 (release on failure): monkeypatch `Ledger.save` to raise for one call; assert the exception propagates and a following non-blocking `fcntl.flock(..., LOCK_EX | LOCK_NB)` probe on the lock file succeeds immediately.
- Property 8 (OS error prevents mutation): monkeypatch `fcntl.flock` (and the Windows path via `msvcrt.locking`, skipped on POSIX CI) to raise `OSError`; assert `append()` propagates it and the ledger file content is byte-identical to before the call.
- Property 9 (deterministic lock path): generate arbitrary path strings via Hypothesis; assert `lock_path_for(p) == lock_path_for(p)` and, for a second distinct path `q != p`, `lock_path_for(p) != lock_path_for(q)`.

Extend `tests/test_config_validation.py` (or a new `tests/test_config_sanity_validator.py`):
- Property 10 (blank fields): `st.text(alphabet=" \t\n", min_size=0, max_size=10)` for blank strings in either field; assert errors and `valid == (len(errors) == 0)`.
- Property 11 (creatability model): build a temp directory tree with Hypothesis-generated nested relative path segments (`st.lists(st.from_regex(r"[A-Za-z0-9_-]{1,10}", fullmatch=True), min_size=1, max_size=5)`), randomly decide whether to pre-create some prefix of the segments, and randomly `chmod` the deepest existing ancestor to remove write permission; compute the reference expectation independently in the test and compare against the validator's result; assert the target path does not exist on disk afterward.

### Example-based / unit tests

- `config_sanity_validator` is a distinct callable from `validate_environment` and returns a `ValidationResult` instance (Requirement 4.1).
- `config_sanity_validator` never calls `shutil.which` or `validate_environment` (Requirement 4.8), verified with `unittest.mock.patch` assertions.
- CLI wiring tests using Click's `CliRunner` for each of `config`, `ledger`, `resume`, `work`, parametrized over: (a) invalid Config (blank workspace, blank vault, non-creatable workspace) → asserts non-zero exit, `_print_validation`-style error output, and the command's main action never invoked; (b) valid Config → asserts the command's main action *is* invoked (Requirements 5.1–5.6).
- `work`-specific test: with `--skip-validation` and a sanity-invalid Config, assert it still exits non-zero from the sanity check (not from `validate_environment`, which should never run); with `--skip-validation` and a sanity-valid Config, assert `validate_environment` is not called while `config_sanity_validator` is (Requirement 5.7).

### Property Test Configuration

- Minimum 100 iterations per property test via `@settings(max_examples=100)`, matching existing convention.
- Each property test's docstring cites `**Validates: Requirements X.Y**` and is tagged in comments as `Feature: safe-persistence-and-config-validation, Property N: <title>`.
- Filesystem-touching property tests use `tempfile.mkdtemp()` per test (via `setup_method`/fixtures) so Hypothesis shrinking never leaks state between examples, matching `tests/test_ledger.py`'s existing pattern.
