# Contributing to Autopilot

A concise guide to the project conventions for human and automated contributors.

## Architecture and Dependency Rule

The project follows Clean Architecture with three layers:

```
domain/          # Entities, value objects, and interfaces. No external dependencies.
application/     # Use cases, orchestration, and registries. Depends only on domain/.
infrastructure/  # Agents, tools, adapters, and persistence. Implements domain interfaces.
cli/             # Click CLI. The outermost layer may depend on any layer.
```

Dependencies always point inward (`infrastructure` → `application` → `domain`).
The domain never imports application or infrastructure, and application never imports
infrastructure. This is enforced by
[tests/test_domain_import_constraint.py](tests/test_domain_import_constraint.py) and
[tests/test_application_import_constraint.py](tests/test_application_import_constraint.py).

## Code Conventions

1. Avoid comments that merely narrate the code. Public functions and classes should have concise docstrings.
2. Add type hints to all public functions.
3. Use dataclasses for entities and value objects.
4. Return `ToolResult` consistently from tools (`success`, `data`, `error`).
5. Define new external dependencies as Protocols or ABCs in `domain/interfaces/` before implementing them in `infrastructure/`.

## Tests

```bash
python3 -m pytest -q
python3 -m pytest -v tests/test_file.py
```

- Tests for Git operations that depend on `Path.cwd()` should use
  `monkeypatch.chdir(tmp_path)` with a real temporary Git repository.
- Use Hypothesis for persistence invariants.
- After adding imports in `domain/` or `application/`, run the import constraint tests.

## Linters

Install development dependencies with `pip install -e ".[dev]"`, then run:

```bash
ruff check autopilot tests
ruff format --check autopilot tests
```

## Pull Requests

- Cover behavior changes to agents or tools with tests.
- Keep the [roadmap](README.md#roadmap--whats-left-to-improve) synchronized with implementation changes.
- Use generic ticket prefixes such as `PROJ-123` and `ACME-456`; do not introduce real customer or company names in examples.
