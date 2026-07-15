# Implementation Plan: Safe Persistence and Config Validation

## Overview

Implement crash-safe atomic JSON writes for `Ledger` and `RunRecordStore`, a cross-platform advisory file lock to serialize concurrent ledger appends, and a lightweight stdlib-only `config_sanity_validator` wired into the `config`, `ledger`, `resume`, and `work` CLI commands immediately after `create_application()`. Implementation is in Python 3.11+, following existing project conventions (`unittest`-style test classes with `setup_method`/`tempfile.mkdtemp()`, Hypothesis property tests with `@settings(max_examples=100)`).

## Tasks

- [x] 1. Implement shared atomic write helper
  - [x] 1.1 Create `autopilot/infrastructure/persistence/atomic_write.py` with `atomic_write_json(path, data, *, indent=2)` and `_remove_if_exists(path)`
    - Use `tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp")` to create a uniquely named temp file in the destination directory
    - Write JSON via `json.dump`, flush, `os.fsync`, and close before `os.replace()`
    - On write/serialization failure: remove the temp file (swallowing only `FileNotFoundError`) and re-raise the original error, leaving the destination untouched
    - On `os.replace()` failure: propagate the error without any cleanup, leaving both temp file and destination untouched
    - Ensure destination parent directory is created via `mkdir(parents=True, exist_ok=True)`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 1.2 Write property test for atomic write round-trip
    - **Property 1: Successful atomic write round-trips arbitrary JSON-serializable data**
    - **Validates: Requirements 1.6, 2.7**
    - New file `tests/test_atomic_write.py`; use `st.recursive` over dicts/lists/text/numbers/booleans/None and arbitrary filenames

  - [ ]* 1.3 Write property test for write-time failure cleanup
    - **Property 2: Write-time failure leaves the destination untouched and cleans up the temp file**
    - **Validates: Requirements 1.4, 2.5**
    - Monkeypatch `json.dump` to raise partway through; assert destination unchanged and no `*.tmp` files remain

  - [ ]* 1.4 Write property test for replace-time failure
    - **Property 3: Replace-time failure leaves both the temp file and destination untouched**
    - **Validates: Requirements 1.5, 2.6**
    - Monkeypatch `os.replace` to raise; assert destination unchanged and exactly one temp file remains

- [x] 2. Migrate `Ledger.save()` to atomic writes
  - [x] 2.1 Update `autopilot/infrastructure/persistence/ledger.py` to import and use `atomic_write_json` in `save()`, replacing the direct `open()`/`json.dump()` calls
    - Keep `self._path.parent.mkdir(parents=True, exist_ok=True)` before the atomic write call
    - _Requirements: 1.1, 1.2, 1.3, 1.6_

  - [x]* 2.2 Write unit tests for `Ledger.save()` atomicity
    - Extend `tests/test_ledger.py` to verify `save()` produces valid, parseable JSON equal to the data saved, using the existing `setup_method`/`tempfile.mkdtemp()` pattern
    - _Requirements: 1.6_

- [x] 3. Migrate `RunRecordStore.save()` to atomic writes
  - [x] 3.1 Update `autopilot/infrastructure/persistence/run_record_store.py` to import and use `atomic_write_json` in `save()`, replacing the direct `open()`/`json.dump()` calls
    - Keep `run_dir.mkdir(parents=True, exist_ok=True)` before the atomic write call so the run directory (and any missing parents, including `runs/`) is created first
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.7_

  - [ ]* 3.2 Write property test for run directory creation
    - **Property 4: Run record save creates missing run directories**
    - **Validates: Requirements 2.1**
    - New or extended file `tests/test_run_record_store.py`; generate random safe run_id strings where `runs/` does not yet exist; assert `save()` creates it and a readable `run-record.json`

  - [x]* 3.3 Write unit tests for `RunRecordStore.save()` atomicity
    - Verify `save()` produces valid, parseable JSON after a successful save
    - _Requirements: 2.7_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement cross-platform advisory file lock
  - [x] 5.1 Create `autopilot/infrastructure/persistence/file_lock.py` with `LedgerLock` context manager and `lock_path_for(target_path)` function
    - Import `fcntl` (POSIX) and `msvcrt` (Windows) with `try/except ImportError` fallback to `None`
    - `__enter__`: create parent dirs, open the lock file in `"a+b"` mode, acquire exclusive blocking lock via `fcntl.flock(..., LOCK_EX)` or `msvcrt.locking(..., LK_LOCK, 1)`; if neither module is available, raise `OSError`; on any exception during acquisition, close the file handle and re-raise before entering the `with` block body
    - `__exit__`: release the lock (`LOCK_UN` / `LK_UNLCK`) inside a `finally` that always closes the file handle, returning `False` so exceptions propagate
    - `lock_path_for(target_path)`: pure function returning `Path(str(target_path) + ".lock")`, deterministic for identical inputs
    - _Requirements: 3.1, 3.3, 3.6, 3.7_

  - [ ]* 5.2 Write property test for deterministic lock path derivation
    - **Property 9: Lock path is a deterministic function of the ledger path**
    - **Validates: Requirements 3.7**
    - New file `tests/test_ledger_lock.py`; generate arbitrary path strings via Hypothesis; assert `lock_path_for(p) == lock_path_for(p)` and differs for a distinct `q`

  - [ ]* 5.3 Write property test for OS-level lock errors preventing mutation
    - **Property 8: Lock acquisition/release OS errors prevent any ledger mutation**
    - **Validates: Requirements 3.6**
    - Monkeypatch `fcntl.flock` to raise `OSError`; assert the error propagates and no load/modify/save step executes (deferred integration with `Ledger.append()` covered in task 6.3, but the raw `LedgerLock` failure-mode behavior is covered here)

- [x] 6. Wire `LedgerLock` into `Ledger.append()`
  - [x] 6.1 Update `autopilot/infrastructure/persistence/ledger.py` constructor to compute `self._lock_path = lock_path_for(self._path)`, and wrap the load-modify-save body of `append()` in `with LedgerLock(self._lock_path):`
    - Preserve existing validation-warning printing before the lock is acquired
    - Ensure the lock is acquired before the load step and held through load, modify, and save
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 6.2 Write property test for no lost updates under concurrent appends
    - **Property 5: Concurrent ledger appends never lose entries**
    - **Validates: Requirements 3.1, 3.2**
    - Use `ThreadPoolExecutor` to fire N `Ledger.append()` calls concurrently against the same ledger path with distinct `run_id`s; assert the final ledger has exactly N entries covering all run_ids

  - [ ]* 6.3 Write property test for lock release on success and on failure
    - **Property 6: Lock is released after a successful append** — **Validates: Requirements 3.4**
    - **Property 7: Lock is released after a failed append** — **Validates: Requirements 3.5**
    - For Property 6: repeated sequential `append()` calls each complete within a short timeout
    - For Property 7: monkeypatch `Ledger.save` to raise for one call; assert the exception propagates and a subsequent non-blocking `fcntl.flock(..., LOCK_EX | LOCK_NB)` probe on the lock file succeeds immediately

  - [ ]* 6.4 Write property test for full append-path OS lock error propagation
    - **Property 8: Lock acquisition/release OS errors prevent any ledger mutation**
    - **Validates: Requirements 3.6**
    - Monkeypatch `fcntl.flock` during `Ledger.append()`; assert the error propagates and the ledger file content is byte-identical to before the call

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement `config_sanity_validator`
  - [x] 8.1 Add `config_sanity_validator(config)` and `_is_creatable_path(path_str)` to `autopilot/infrastructure/validators.py`
    - `config_sanity_validator`: check `workspace_location` and `vault_location` are non-blank (add error per field if blank); if `workspace_location` is non-blank, call `_is_creatable_path` and add a descriptive error if not creatable; return the resulting `ValidationResult`
    - `_is_creatable_path`: return `(True, "")` if the path exists as a directory; return `(False, reason)` if it exists but is not a directory; otherwise walk up `path.parent` to the nearest existing ancestor and check it is a directory and writable via `os.access(ancestor, os.W_OK)`; catch `OSError` and return `(False, reason)`; never call `mkdir`
    - Do not call `validate_environment`, `shutil.which`, or read Jira env vars
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ]* 8.2 Write property test for blank field rejection and validity consistency
    - **Property 10: Blank location fields are rejected and validity reflects error state**
    - **Validates: Requirements 4.2, 4.3, 4.7**
    - New or extended file `tests/test_config_sanity_validator.py`; use `st.text(alphabet=" \t\n", min_size=0, max_size=10)` for blank strings in either field; assert errors mention the field and `valid == (len(errors) == 0)`

  - [ ]* 8.3 Write property test for creatability model correctness
    - **Property 11: Workspace creatability check matches the nearest-existing-ancestor model, without side effects**
    - **Validates: Requirements 4.4, 4.5, 4.6**
    - Build a temp directory tree with Hypothesis-generated nested relative path segments, randomly pre-create a prefix of segments, randomly remove write permission on the deepest existing ancestor; compute an independent reference expectation in the test and compare; assert the target path does not exist on disk afterward

  - [x]* 8.4 Write unit tests for `config_sanity_validator` independence from `validate_environment`
    - Assert `config_sanity_validator` is a distinct callable returning a `ValidationResult` instance
    - Use `unittest.mock.patch` to assert `shutil.which` and `validate_environment` are never called
    - _Requirements: 4.1, 4.8_

- [x] 9. Wire `config_sanity_validator` into CLI commands
  - [x] 9.1 Update `autopilot/cli/commands.py`: import `config_sanity_validator` and insert the sanity check immediately after `create_application()` in the `config` command, before `app.config_command.execute()`
    - `sanity = config_sanity_validator(app.config)`; if `_print_validation(sanity)` returns `True`, `sys.exit(1)` before any other Config read
    - _Requirements: 5.1, 5.5, 5.6_

  - [x] 9.2 Insert the same sanity check immediately after `create_application()` in the `ledger` command, before `app.ledger.get_by_ticket(...)` / `app.ledger.summary()`
    - _Requirements: 5.2, 5.5, 5.6_

  - [x] 9.3 Insert the same sanity check immediately after `create_application()` in the `resume` command, before `app.resume_command.execute()`
    - _Requirements: 5.3, 5.5, 5.6_

  - [x] 9.4 Insert the same sanity check immediately after `create_application()` in the `work` command, before the existing `skip_validation` branch that calls `validate_environment`, running unconditionally regardless of `--skip-validation`
    - _Requirements: 5.4, 5.5, 5.6, 5.7_

  - [x]* 9.5 Write CLI wiring tests using Click's `CliRunner`
    - Parametrize over `config`, `ledger`, `resume`, `work`: (a) invalid Config (blank workspace, blank vault, non-creatable workspace) → assert non-zero exit and the command's main action never invoked; (b) valid Config → assert the command's main action is invoked
    - New or extended file `tests/test_integration_cli.py`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x]* 9.6 Write `work`-specific `--skip-validation` interaction test
    - With `--skip-validation` and a sanity-invalid Config: assert exit is non-zero from the sanity check and `validate_environment` is never called
    - With `--skip-validation` and a sanity-valid Config: assert `validate_environment` is not called while `config_sanity_validator` is called
    - _Requirements: 5.7_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP; they are not implemented by the coding agent per workflow rules.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation of the persistence layer, the locking layer, and the CLI wiring independently.
- Property tests validate the 11 correctness properties defined in the design document; unit tests validate specific examples and edge cases.
- All new code is stdlib-only (no third-party locking dependency), matching the existing project convention.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "8.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "2.1", "3.1", "5.1", "8.2", "8.3", "8.4"] },
    { "id": 2, "tasks": ["2.2", "3.2", "3.3", "5.2", "5.3"] },
    { "id": 3, "tasks": ["6.1"] },
    { "id": 4, "tasks": ["6.2", "6.3", "6.4"] },
    { "id": 5, "tasks": ["9.1"] },
    { "id": 6, "tasks": ["9.2"] },
    { "id": 7, "tasks": ["9.3"] },
    { "id": 8, "tasks": ["9.4"] },
    { "id": 9, "tasks": ["9.5", "9.6"] }
  ]
}
```
