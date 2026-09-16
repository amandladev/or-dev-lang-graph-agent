# Task Manager CLI

Design reference for the DFX5 task manager CLI feature.

## Module

- File: `src/todo.py`
- All logic lives in plain functions operating on `list[dict]`:
  - `add_task(tasks, description)` — appends `{"description": ..., "done": False}` with a unique sequential id.
  - `complete_task(tasks, task_id)` — marks the task as done; raises `ValueError` when the id is unknown.
  - `list_tasks(tasks)` — pending tasks first, then completed ones.
  - `stats(tasks)` — dict with `total`, `pending`, `done` counts.

## CLI

- File: `bin/todo`, executable, shebang `#!/usr/bin/env python3`.
- argparse subcommands: `add <description>`, `list`, `done <id>`, `stats`.
- Persists to `tasks.json` in the current directory (stdlib `json`).
- No third-party dependencies.

## Tests

- File: `tests/test_todo.py`
- Covers add, complete (including the not-found `ValueError`), ordering
  (pending first) and stats counts.