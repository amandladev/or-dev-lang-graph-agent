# Implementation Plan: Publisher Shell Injection Fix

## Overview

Convert the feature design into a series of prompts for a code-generation LLM that will implement each step with incremental progress. Make sure that each prompt builds on the previous prompts, and ends with wiring things together. There should be no hanging or orphaned code that isn't integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing code.

All changes are scoped to `autopilot/infrastructure/agents/publisher.py` (implementation) and the new `tests/test_publisher_git_safety.py` (tests). Work proceeds in this order: add the two pure sanitization helpers first (they have no dependencies and are the easiest to property-test in isolation), then refactor `_git_cmd` to be list-based, then refactor `_execute_git_workflow` to wire the sanitized values and list-based `_git_cmd` together with stop-on-first-failure semantics.

## Tasks

- [x] 1. Implement branch slug sanitization
  - [x] 1.1 Implement `_sanitize_branch_slug` in `publisher.py`
    - Add module-level regex `_DISALLOWED_RUN = re.compile(r"[^a-z0-9]+")` and the `_sanitize_branch_slug(title: str) -> str` static/pure helper per the design's algorithm: lowercase, collapse any run of non `[a-z0-9]` characters to a single hyphen, strip leading/trailing hyphens, fall back to `"implementation"` if empty, truncate to 30 code points, and re-strip a trailing hyphen left by truncation
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x]* 1.2 Write property test for no-uppercase guarantee
    - **Property 3: Branch slugs contain no uppercase ASCII letters**
    - **Validates: Requirements 2.1**

  - [x]* 1.3 Write property test for slug charset
    - **Property 4: Branch slugs use only lowercase alphanumerics and hyphens**
    - **Validates: Requirements 2.2**

  - [x]* 1.4 Write property test for no consecutive hyphens
    - **Property 5: Branch slugs never contain consecutive hyphens**
    - **Validates: Requirements 2.3**

  - [x]* 1.5 Write property test for no leading/trailing hyphen
    - **Property 6: Branch slugs never start or end with a hyphen**
    - **Validates: Requirements 2.4, 2.7**

  - [x]* 1.6 Write property test for empty-title fallback
    - **Property 7: Titles that sanitize to nothing fall back to "implementation"**
    - **Validates: Requirements 2.5**

  - [x]* 1.7 Write property test for max length
    - **Property 8: Branch slugs never exceed 30 code points**
    - **Validates: Requirements 2.6**

  - [x]* 1.8 Write unit tests for `_sanitize_branch_slug` edge cases
    - Cover `"Fix Login Bug"` → `"fix-login-bug"`, `""` → `"implementation"`, `"!!!"` → `"implementation"`, a 40-character title truncating to 30 characters, and a title engineered so truncation lands exactly on a hyphen
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 2. Implement commit message sanitization
  - [x] 2.1 Implement `_sanitize_commit_message` in `publisher.py`
    - Add module-level regex `_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")` and the `_sanitize_commit_message(message: str) -> str` pure helper: strip all `U+0000`-`U+001F` and `U+007F` characters (preserving space), and substitute `"Automated commit"` if the result is empty or whitespace-only
    - _Requirements: 3.1, 3.2, 3.3_

  - [x]* 2.2 Write property test for control-character removal
    - **Property 9: Commit messages contain no control characters**
    - **Validates: Requirements 3.1, 3.2**

  - [x]* 2.3 Write property test for empty-message fallback
    - **Property 10: Empty or whitespace-only sanitized messages fall back to "Automated commit"**
    - **Validates: Requirements 3.3**

  - [x]* 2.4 Write unit tests for `_sanitize_commit_message` edge cases
    - Cover `"feat: add x\r\ny"` → `"feat: add xy"`, `"\x00\x01\x1f\x7f"` → `"Automated commit"`, and `"   "` → `"Automated commit"`
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 3. Checkpoint - Ensure sanitization helper tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Refactor `_git_cmd` for list-based subprocess execution
  - [x] 4.1 Refactor `_git_cmd` to accept a list of arguments and run without a shell
    - Change the signature to `_git_cmd(self, args: list[str], results: dict) -> bool`, build `command = ["git", *args]`, call `subprocess.run(command, shell=False, capture_output=True, text=True, timeout=30, cwd=str(Path.cwd()))`, append an operations entry with `"command": command` (the list itself, never joined), `"success": result.returncode == 0`, and `"output": result.stdout.strip() or result.stderr.strip()`; narrow the exception handler to `except Exception as e` and log a failed operation with `"output": str(e)` before returning `False`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 5.2, 5.3, 5.4, 5.6_

  - [x]* 4.2 Write property test for shell-less subprocess invocation
    - **Property 1: subprocess.run is invoked without a shell**
    - **Validates: Requirements 1.1, 1.4**

  - [x]* 4.3 Write property test for exact argument list logging
    - **Property 2: Operations log stores the exact argument list**
    - **Validates: Requirements 1.3, 5.2**

  - [x]* 4.4 Write property test for success flag correctness
    - **Property 13: Logged success reflects the exit code**
    - **Validates: Requirements 5.3**

  - [x]* 4.5 Write property test for output capture correctness
    - **Property 14: Logged output reflects captured stdout/stderr**
    - **Validates: Requirements 5.4**

- [x] 5. Refactor `_execute_git_workflow` with sanitization and stop-on-failure
  - [x] 5.1 Refactor `_execute_git_workflow` to build list-based commands from sanitized values and stop at the first failure
    - Compute `branch_slug = self._sanitize_branch_slug(ticket.get("title", "implementation"))`, format `branch_name` from `rules["branch_pattern"]`, and set `results["branch"] = branch_name` immediately; call `_git_cmd` for `["checkout", source]`, `["pull"]`, `["checkout", "-b", branch_name]`, `["add", "-A"]`, checking each boolean return and returning `results` immediately on `False`; format the raw commit message from `rules["commit_pattern"]`, sanitize it with `_sanitize_commit_message`, set `results["commit_message"]` immediately before attempting `["commit", "-m", commit_message]`, then check and stop-on-failure; finally attempt `["push", "-u", remote, branch_name]`
    - _Requirements: 1.2, 3.4, 4.1, 4.2, 4.3, 5.5, 5.7, 5.8_

  - [x]* 5.2 Write property test for commit message as a distinct argument
    - **Property 11: Commit message is a distinct argument element**
    - **Validates: Requirements 3.4**

  - [x]* 5.3 Write property test for stop-on-first-failure behavior
    - **Property 12: Workflow stops at the first failing step**
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [x]* 5.4 Write property test for branch field presence
    - **Property 15: Branch is always populated once computed**
    - **Validates: Requirements 5.5**

  - [x]* 5.5 Write property test for commit_message field conditional presence
    - **Property 16: Commit message presence matches whether the commit step was attempted**
    - **Validates: Requirements 5.7, 5.8**

  - [x]* 5.6 Write unit tests for `_execute_git_workflow` scenarios
    - Cover: all six steps mocked to succeed (full 6-entry operations log, `"branch"` and `"commit_message"` both set); the source-checkout step mocked to fail (1-entry log, `"branch"` set, `"commit_message"` absent); and a title containing shell metacharacters (e.g. `` "fix `rm -rf /` bug" ``) producing a branch name with no backticks, semicolons, `$`, or spaces, demonstrating the mocked `subprocess.run` call receives it as a single list element
    - _Requirements: 1.1, 1.2, 4.1, 4.2, 4.3, 5.5, 5.7, 5.8_

- [x] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP, but are recommended here since the design's Correctness Properties section maps directly to these tests
- All test tasks target the single new file `tests/test_publisher_git_safety.py`, following the `pytest` + `Hypothesis` conventions in `tests/test_config_validation.py` (docstring property references, `@settings(max_examples=100)`, `@given(...)`)
- Property tests mock `subprocess.run` via `unittest.mock.patch` so no real git process is spawned
- `_load_rules`, `_parse_rules`, `_default_rules`, and `_update_jira` are unchanged by this feature and are out of scope

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "1.2"] },
    { "id": 2, "tasks": ["4.1", "1.3"] },
    { "id": 3, "tasks": ["5.1", "1.4"] },
    { "id": 4, "tasks": ["1.5"] },
    { "id": 5, "tasks": ["1.6"] },
    { "id": 6, "tasks": ["1.7"] },
    { "id": 7, "tasks": ["1.8"] },
    { "id": 8, "tasks": ["2.2"] },
    { "id": 9, "tasks": ["2.3"] },
    { "id": 10, "tasks": ["2.4"] },
    { "id": 11, "tasks": ["4.2"] },
    { "id": 12, "tasks": ["4.3"] },
    { "id": 13, "tasks": ["4.4"] },
    { "id": 14, "tasks": ["4.5"] },
    { "id": 15, "tasks": ["5.2"] },
    { "id": 16, "tasks": ["5.3"] },
    { "id": 17, "tasks": ["5.4"] },
    { "id": 18, "tasks": ["5.5"] },
    { "id": 19, "tasks": ["5.6"] }
  ]
}
```
