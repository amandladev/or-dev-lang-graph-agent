# DFX5 Feature Conventions

This document describes how features are implemented in DFX5 projects.

## Rules

- Features must be implemented in the `src/` directory as standalone modules.
- Use only the Python standard library — never add third-party dependencies.
- CLI tools must expose argparse subcommands and live in `bin/` as an
  executable script with a shebang.
- Every feature must include pytest tests in the `tests/` directory.
- Tests must pass with `python3 -m pytest`.
- Keep changes minimal and follow the existing code style.
- Update README.md with usage documentation for user-facing features.

## Example

A task manager CLI exposes subcommands `add`, `list`, `done` and `stats`,
persists data to `tasks.json` with the standard json module, and keeps all
logic in `src/todo.py` so it can be unit tested.