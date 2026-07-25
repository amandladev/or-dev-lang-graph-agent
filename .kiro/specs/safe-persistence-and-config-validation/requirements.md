# Requirements Document

## Introduction

Autopilot persists audit and execution data as plain JSON files (`ledger.json` via `Ledger`, and `run-record.json` via `RunRecordStore`) using direct `open()`/`json.dump()` calls with no atomicity or inter-process coordination. A crash or a concurrent `autopilot` process writing at the same time can leave these files truncated, partially written, or interleaved with another process's write. Separately, only the `work` CLI command validates configuration (via `validate_environment`) before use; the `config`, `ledger`, and `resume` commands call `create_application()` directly, so a misconfigured `workspace_location` or `vault_location` surfaces as a raw exception/traceback instead of a clear message.

This feature introduces (1) atomic, crash-safe writes for the ledger and run record JSON files, (2) an advisory file lock around the ledger's read-modify-write append cycle to prevent corruption or lost updates when multiple Autopilot processes run concurrently, and (3) a new lightweight, stdlib-only config-sanity validator — distinct from and lighter than `validate_environment` — that checks `workspace_location` and `vault_location` are non-empty and that `workspace_location` is creatable, invoked consistently by the `config`, `ledger`, `resume`, and `work` CLI commands immediately after `create_application()`.

## Glossary

- **Ledger**: The `Ledger` class in `autopilot/infrastructure/persistence/ledger.py`, responsible for loading, saving, and appending audit entries to `ledger.json`.
- **Run_Record_Store**: The `RunRecordStore` class in `autopilot/infrastructure/persistence/run_record_store.py`, responsible for saving and loading `run-record.json` files under `{workspace}/runs/{run_id}/`.
- **Atomic_Write**: A save operation that writes JSON content to a temporary file in the same directory as the destination file, flushes and closes it, then uses `os.replace()` to move it into place, so that the destination file is never observed in a partially-written state and any pre-existing destination file remains intact if the write fails before the replace step.
- **Ledger_Lock**: An advisory, stdlib-only file lock (using `fcntl.flock` on POSIX platforms and `msvcrt.locking` on Windows) that a process holds for the entire duration of the Ledger's load-modify-write append cycle, to serialize concurrent append operations across processes.
- **Config_Sanity_Validator**: A new function, distinct from `validate_environment`, that performs a lightweight, fast check of `workspace_location` and `vault_location` on a `Config` object and returns a `ValidationResult`.
- **Validation_Result**: The existing `ValidationResult` dataclass in `autopilot/infrastructure/validators.py`, exposing `valid`, `errors`, and `warnings`, consumed by the CLI's `_print_validation` helper.
- **CLI_Command**: One of the `config`, `ledger`, `resume`, or `work` Click commands defined in `autopilot/cli/commands.py`.

## Requirements

### Requirement 1: Atomic ledger writes

**User Story:** As a developer relying on the audit ledger, I want `ledger.json` writes to be atomic, so that a crash or interruption during a save cannot leave the ledger file truncated or corrupted.

#### Acceptance Criteria

1. WHEN the Ledger saves data, THE Ledger SHALL perform an Atomic_Write by first writing the complete serialized JSON content, encoded as UTF-8, to a uniquely named temporary file located in the same directory as the destination `ledger.json` file, such that the temporary file's name is distinguishable from `ledger.json` and does not collide with any other temporary file the Ledger creates concurrently.
2. WHEN the Ledger writes the temporary file during an Atomic_Write, THE Ledger SHALL flush the temporary file's contents and close its file handle before performing the replace step.
3. WHEN the temporary file has been fully written and closed, THE Ledger SHALL use `os.replace()` to move the temporary file to the destination `ledger.json` path, replacing any pre-existing file at that path.
4. IF the data cannot be serialized to JSON, or an error occurs while writing to the temporary file during an Atomic_Write, THEN THE Ledger SHALL delete the temporary file if it was created, SHALL leave any pre-existing `ledger.json` file unmodified, and SHALL propagate the error to the caller rather than discarding it silently.
5. IF an error occurs during the `os.replace()` step of an Atomic_Write, THEN THE Ledger SHALL leave the temporary file and any pre-existing `ledger.json` file unmodified, and SHALL propagate the error to the caller.
6. WHEN the Ledger completes a save operation successfully, THE Ledger SHALL result in a `ledger.json` file whose content is valid JSON, parseable without error, and equal to the data most recently saved.

### Requirement 2: Atomic run record writes

**User Story:** As a developer relying on run records for audit and resume, I want `run-record.json` writes to be atomic, so that a crash during a save cannot leave a run record file truncated or corrupted.

#### Acceptance Criteria

1. WHEN the Run_Record_Store saves a run record for a run_id whose run directory does not yet exist, THE Run_Record_Store SHALL create that directory, including any missing parent directories, before performing the Atomic_Write.
2. WHEN the Run_Record_Store saves a run record, THE Run_Record_Store SHALL perform an Atomic_Write by first writing the complete serialized JSON content to a temporary file located in the same directory as the destination `run-record.json` file.
3. WHEN the Run_Record_Store writes the temporary file during an Atomic_Write, THE Run_Record_Store SHALL flush the temporary file's contents and close its file handle before performing the replace step.
4. WHEN the temporary file has been fully written and closed, THE Run_Record_Store SHALL use `os.replace()` to move the temporary file to the destination `run-record.json` path.
5. IF an error occurs while writing the temporary file during an Atomic_Write, THEN THE Run_Record_Store SHALL remove the temporary file if it still exists and SHALL leave any pre-existing `run-record.json` file unmodified.
6. IF an error occurs during the `os.replace()` step of an Atomic_Write, THEN THE Run_Record_Store SHALL leave the temporary file and any pre-existing `run-record.json` file unmodified, and SHALL propagate the error to the caller.
7. WHEN the Run_Record_Store completes a save operation successfully, THE Run_Record_Store SHALL result in a `run-record.json` file whose content is valid JSON parseable without error.

### Requirement 3: Concurrency-safe ledger append

**User Story:** As a developer running multiple Autopilot workflows in parallel, I want ledger append operations to be coordinated across processes, so that concurrent appends do not interleave or overwrite each other's entries.

#### Acceptance Criteria

1. WHEN the Ledger begins an append operation, THE Ledger SHALL acquire a Ledger_Lock before performing the load step of the load-modify-write cycle, blocking indefinitely until the lock is acquired rather than failing or timing out due to contention.
2. WHILE the Ledger holds the Ledger_Lock, THE Ledger SHALL complete the load, modify, and save steps of the append operation before releasing the Ledger_Lock.
3. THE Ledger SHALL use only Python standard-library facilities (`fcntl` on POSIX platforms, `msvcrt` on Windows) to acquire and release the Ledger_Lock, without introducing a third-party locking dependency.
4. WHEN the Ledger's append operation completes normally, THE Ledger SHALL release the Ledger_Lock.
5. IF an exception is raised during the load, modify, or save steps of the append operation, THEN THE Ledger SHALL release the Ledger_Lock before the exception propagates to the caller.
6. IF the Ledger is unable to acquire or release the Ledger_Lock due to an operating-system-level error (for example, an unsupported platform or a permissions failure), THEN THE Ledger SHALL propagate that error to the caller without performing the load, modify, or save steps of the append operation.
7. THE Ledger SHALL derive the Ledger_Lock's lock file path deterministically from the ledger's configured file path, such that two Ledger instances constructed with the same `ledger_path` always compute the same lock file path and therefore contend for the same Ledger_Lock.

### Requirement 4: Lightweight config-sanity validator

**User Story:** As a developer running any Autopilot CLI command, I want a fast sanity check of core configuration values, so that a misconfigured workspace or vault location produces a clear message instead of a cryptic downstream error.

#### Acceptance Criteria

1. THE Config_Sanity_Validator SHALL be implemented as a function distinct from `validate_environment`, accepting a `Config` object and returning a Validation_Result.
2. IF the `workspace_location` field of the supplied Config is an empty string or a string containing only whitespace, THEN THE Config_Sanity_Validator SHALL add an error to the returned Validation_Result.
3. IF the `vault_location` field of the supplied Config is an empty string or a string containing only whitespace, THEN THE Config_Sanity_Validator SHALL add an error to the returned Validation_Result.
4. IF the `workspace_location` field of the supplied Config is non-empty, THEN THE Config_Sanity_Validator SHALL determine whether that path is creatable by checking that the path already exists as a directory, or, if it does not exist, by walking up to the nearest existing ancestor directory and checking that the ancestor is a writable directory.
5. IF the `workspace_location` path is non-empty but is not creatable (for example, an existing file occupies that path, an existing ancestor directory is not writable, or a filesystem error such as a permissions failure occurs while performing the creatability check), THEN THE Config_Sanity_Validator SHALL add an error to the returned Validation_Result describing why the path is not creatable.
6. THE Config_Sanity_Validator SHALL NOT create the `workspace_location` directory as a side effect of validation.
7. THE Config_Sanity_Validator SHALL return a Validation_Result whose `valid` field is `false` when one or more errors have been added, and `true` otherwise.
8. THE Config_Sanity_Validator SHALL complete its checks without invoking `validate_environment` and without checking for the availability of `opencode`, `git`, or Jira credentials.

### Requirement 5: Consistent invocation across CLI commands

**User Story:** As a developer using any Autopilot CLI command, I want configuration sanity checked immediately after the application is created, so that all commands behave consistently when configuration is invalid.

#### Acceptance Criteria

1. WHEN the `config` CLI_Command creates the application via `create_application()`, THE `config` CLI_Command SHALL invoke the Config_Sanity_Validator on the resulting Config before performing any other operation that reads from that Config.
2. WHEN the `ledger` CLI_Command creates the application via `create_application()`, THE `ledger` CLI_Command SHALL invoke the Config_Sanity_Validator on the resulting Config before performing any other operation that reads from that Config.
3. WHEN the `resume` CLI_Command creates the application via `create_application()`, THE `resume` CLI_Command SHALL invoke the Config_Sanity_Validator on the resulting Config before performing any other operation that reads from that Config.
4. WHEN the `work` CLI_Command creates the application via `create_application()`, THE `work` CLI_Command SHALL invoke the Config_Sanity_Validator on the resulting Config before performing any other operation that reads from that Config, including before the existing `validate_environment` check, regardless of whether the `--skip-validation` flag is set.
5. IF the Config_Sanity_Validator returns a Validation_Result with one or more errors, THEN THE CLI_Command SHALL pass that Validation_Result to the existing `_print_validation` helper, SHALL exit with a non-zero status code, and SHALL NOT perform any subsequent validation (including `validate_environment` for the `work` CLI_Command) or the command's main action.
6. IF the Config_Sanity_Validator returns a Validation_Result with no errors, THEN THE CLI_Command SHALL print any warnings via `_print_validation` and SHALL proceed: the `config` CLI_Command SHALL display the configuration, the `ledger` CLI_Command SHALL display the ledger summary, the `resume` CLI_Command SHALL resume the workflow, and the `work` CLI_Command SHALL proceed to its `validate_environment` check (unless `--skip-validation` is set) followed by workflow execution.
7. WHERE the `--skip-validation` flag is passed to the `work` CLI_Command, THE `work` CLI_Command SHALL still invoke the Config_Sanity_Validator, and SHALL only skip the `validate_environment` check.
