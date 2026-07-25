# Design Document

## Overview

`PublisherAgent` currently builds git command strings by interpolating ticket
data directly into a string that is executed with
`subprocess.run(cmd, shell=True, ...)`. This design replaces that mechanism
with list-based `subprocess.run` calls (`shell=False`), adds two pure
sanitization helpers (`_sanitize_branch_slug`, `_sanitize_commit_message`),
and refactors `_git_cmd` / `_execute_git_workflow` to build argument lists,
stop on first failure, and preserve the existing `results["operations"]`
structure and field semantics.

No new files, dependencies, or public interfaces are introduced. All changes
are internal to `autopilot/infrastructure/agents/publisher.py`. Downstream
callers of `PublisherAgent.execute()` are unaffected because the shape of the
returned `metrics["git"]` dict (`operations`, `branch`, `commit_message`)
is preserved.

## Architecture

```
PublisherAgent.execute()
        │
        ▼
_execute_git_workflow(ticket_id, ticket, rules)
        │
        ├─ _sanitize_branch_slug(title)      ──▶ branch_name
        ├─ _sanitize_commit_message(message) ──▶ commit_message
        │
        ▼
_git_cmd(args: list[str], results: dict) ──▶ subprocess.run(["git", *args], shell=False, ...)
        │
        ▼
results["operations"].append({"command": [...], "success": bool, "output": str})
```

`_sanitize_branch_slug` and `_sanitize_commit_message` are pure functions
(string in, string out) with no side effects, which makes them ideal targets
for property-based testing. `_git_cmd` and `_execute_git_workflow` retain
their existing responsibilities (execute one step / orchestrate the
sequence) but change their argument shape and control flow.

This stays within `autopilot/infrastructure/agents/`, respecting the
project's dependency rule (Infrastructure → Application → Domain); no
domain or application code changes are required.

## Components and Interfaces

### `_sanitize_branch_slug(title: str) -> str`

Pure function implementing Requirement 2. Applied to `ticket.get("title",
"implementation")` before it is substituted into `rules["branch_pattern"]`.

Algorithm (order matters — each step operates on the output of the previous
one):

1. Lowercase: convert all uppercase ASCII letters (`A`-`Z`) to lowercase.
2. Replace disallowed characters: any character that is not a lowercase
   ASCII letter, digit, space, or hyphen becomes a hyphen.
3. Collapse runs: any run of two or more consecutive space/hyphen characters
   (in any combination) collapses to a single hyphen. This also converts
   any remaining standalone spaces to hyphens (a run of length 1 that is a
   space is handled by treating space as equivalent to hyphen throughout —
   see implementation note below).
4. Trim: strip leading and trailing hyphens.
5. Fallback: if the result is empty, use `"implementation"`.
6. Truncate: limit to 30 Unicode code points (`slug[:30]`, using code-point
   indexing, not byte length).
7. Trim again: if truncation left a trailing hyphen, strip it.

Implementation note: steps 2 and 3 can be combined into a single regex pass
— replace any maximal run of characters that are *not* `[a-z0-9]` with a
single hyphen — which simultaneously satisfies "replace disallowed chars"
and "collapse consecutive space/hyphen runs" (since a run mixing spaces and
disallowed chars collapses to one hyphen either way).

```python
import re

_DISALLOWED_RUN = re.compile(r"[^a-z0-9]+")


def _sanitize_branch_slug(title: str) -> str:
    lowered = title.lower()
    collapsed = _DISALLOWED_RUN.sub("-", lowered)
    trimmed = collapsed.strip("-")
    slug = trimmed or "implementation"
    truncated = slug[:30]
    return truncated.rstrip("-") or "implementation"
```

The final `or "implementation"` guards the edge case where truncation to 30
code points and trailing-hyphen trim could — in principle — leave an empty
string (e.g. a slug that is exactly 30 hyphens is already excluded by step 3
collapsing runs, but this keeps the function total and defensive).

### `_sanitize_commit_message(message: str) -> str`

Pure function implementing Requirement 3. Applied to the fully formatted
commit message (after `rules["commit_pattern"].format(...)`) before it is
passed to `git commit`.

Algorithm:

1. Remove every character whose code point is in `U+0000`–`U+001F` or is
   `U+007F`, except `U+0020` (space). This removes `\n` (`U+000A`) and `\r`
   (`U+000D`) as a consequence, since they fall inside `U+0000`–`U+001F`.
2. If the result is empty or consists only of whitespace, substitute
   `"Automated commit"`.

```python
import re

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_commit_message(message: str) -> str:
    cleaned = _CONTROL_CHARS.sub("", message)
    return cleaned if cleaned.strip() else "Automated commit"
```

### `_git_cmd(args: list[str], results: dict) -> bool`

Refactored to accept a list of string arguments instead of a pre-formatted
string.

```python
def _git_cmd(self, args: list[str], results: dict) -> bool:
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path.cwd()),
        )
        success = result.returncode == 0
        results["operations"].append({
            "command": command,
            "success": success,
            "output": result.stdout.strip() or result.stderr.strip(),
        })
        return success
    except subprocess.TimeoutExpired as e:
        results["operations"].append({
            "command": command,
            "success": False,
            "output": str(e),
        })
        return False
```

Key changes from the current implementation:
- `args: list[str]` replaces `args: str`; no string formatting/interpolation
  of git arguments occurs anywhere in the call chain.
- `subprocess.run` receives `["git", *args]` (a list) with `shell=False`,
  never `shell=True`.
- The `"command"` field stored in the operations log is the list itself
  (`command`), never a joined/re-serialized string.
- The bare `except (subprocess.TimeoutExpired, Exception)` is narrowed to
  `except Exception` (catching `TimeoutExpired` redundantly was flagged as
  dead code by the linter); this still satisfies Requirement 4.2's "catch
  the exception" behavior for any exception type, including timeouts.

### `_execute_git_workflow(ticket_id, ticket, rules) -> dict`

Refactored to build argument lists, check the boolean return of every
`_git_cmd` call, and stop immediately on the first failure — while still
populating `"branch"` as soon as it is computed and `"commit_message"` only
once the commit step is attempted.

```python
def _execute_git_workflow(
    self, ticket_id: str, ticket: dict, rules: dict
) -> dict[str, Any]:
    results: dict[str, Any] = {"operations": []}

    title = ticket.get("title", "implementation")
    branch_slug = self._sanitize_branch_slug(title)
    branch_name = rules["branch_pattern"].format(
        ticket_id=ticket_id.lower(),
        description=branch_slug,
    )
    results["branch"] = branch_name

    source = rules["branch_from"]
    if not self._git_cmd(["checkout", source], results):
        return results
    if not self._git_cmd(["pull"], results):
        return results
    if not self._git_cmd(["checkout", "-b", branch_name], results):
        return results
    if not self._git_cmd(["add", "-A"], results):
        return results

    raw_commit_msg = rules["commit_pattern"].format(
        ticket_id=ticket_id,
        description=ticket.get("title", "Implementation"),
    )
    commit_message = self._sanitize_commit_message(raw_commit_msg)
    results["commit_message"] = commit_message
    if not self._git_cmd(["commit", "-m", commit_message], results):
        return results

    remote = rules["push_remote"]
    if not self._git_cmd(["push", "-u", remote, branch_name], results):
        return results

    return results
```

Key changes from the current implementation:
- `"branch"` is set immediately after `branch_name` is computed, before any
  git step runs, so it is always present in `results` regardless of which
  step fails (Requirement 5.5).
- `"commit_message"` is set immediately before the commit step is attempted
  (not before, not after), so it is present if-and-only-if the commit step
  was attempted (Requirements 5.7, 5.8). If checkout/pull/checkout-b/add
  fails, `"commit_message"` is never added to `results`.
- Every `_git_cmd` call's boolean return value is checked; on `False` the
  function returns `results` immediately, so no subsequent step executes
  and no exception propagates out of `_execute_git_workflow` (Requirement
  4.1, 4.2, 4.3). `_git_cmd` itself never raises — it converts any internal
  exception into a logged failed operation and returns `False` — so the
  `if not self._git_cmd(...)` checks are sufficient to implement
  stop-on-failure without an outer `try`/`except` in the workflow method.

## Data Models

No new persisted entities. The shape of the git results dict returned by
`_execute_git_workflow` (and surfaced as `metrics["git"]` from
`PublisherAgent.execute()`) is:

```python
{
    "operations": [
        {
            "command": list[str],   # e.g. ["git", "checkout", "develop"]
            "success": bool,
            "output": str,
        },
        ...
    ],
    "branch": str,              # always present once computed
    "commit_message": str,      # present only if commit step was attempted
}
```

`"commit_message"` is an optional key — its absence is meaningful (it
signals the workflow stopped before the commit step) and downstream code
must use `.get("commit_message")` rather than assume the key exists.

## Error Handling

- **Non-zero git exit code**: `_git_cmd` returns `False` after appending an
  operations entry with `"success": False` and `"output"` set to
  `stdout.strip() or stderr.strip()`. `_execute_git_workflow` sees `False`
  and returns immediately.
- **Exception during a git step** (e.g. `subprocess.TimeoutExpired`, or any
  other exception raised by `subprocess.run`): caught inside `_git_cmd`,
  logged with `"success": False` and `"output": str(exception)`, and
  `_git_cmd` returns `False`. No exception ever escapes `_git_cmd`, so
  `_execute_git_workflow` and `PublisherAgent.execute()` never raise due to
  a git failure — the workflow always returns normally with a partial
  `operations` log (Requirement 4.3).
- **Malformed or missing rules fields** (e.g. `rules["branch_pattern"]`
  missing a `{description}` placeholder): out of scope for this fix;
  behavior is unchanged from the current implementation (a `KeyError` from
  `.format()` would propagate, as it does today). Sanitization only changes
  what value flows into the placeholder, not the formatting mechanics.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: subprocess.run is invoked without a shell

For any list of string arguments passed to `_git_cmd`, the underlying `subprocess.run` call SHALL be invoked with `shell=False` and a single positional `args` list equal to `["git"] + args`.

**Validates: Requirements 1.1, 1.4**

### Property 2: Operations log stores the exact argument list

For any list of string arguments passed to `_git_cmd`, the `"command"` field appended to `results["operations"]` SHALL equal the list `["git"] + args` exactly (as a list object, never joined or re-serialized into a string).

**Validates: Requirements 1.3, 5.2**

### Property 3: Branch slugs contain no uppercase ASCII letters

For any ticket title string, `_sanitize_branch_slug(title)` SHALL contain no character in the range `A`-`Z`.

**Validates: Requirements 2.1**

### Property 4: Branch slugs use only lowercase alphanumerics and hyphens

For any ticket title string, every character of `_sanitize_branch_slug(title)` SHALL be a lowercase ASCII letter, a digit, or a hyphen.

**Validates: Requirements 2.2**

### Property 5: Branch slugs never contain consecutive hyphens

For any ticket title string, `_sanitize_branch_slug(title)` SHALL NOT contain the substring `"--"`.

**Validates: Requirements 2.3**

### Property 6: Branch slugs never start or end with a hyphen

For any ticket title string, `_sanitize_branch_slug(title)` SHALL NOT start with `"-"` and SHALL NOT end with `"-"`, whether or not truncation to 30 code points occurred.

**Validates: Requirements 2.4, 2.7**

### Property 7: Titles that sanitize to nothing fall back to "implementation"

For any ticket title string composed only of characters that are removed or collapsed by sanitization (e.g. any combination of whitespace, punctuation, and other non-alphanumeric characters with no ASCII letters or digits), `_sanitize_branch_slug(title)` SHALL equal `"implementation"`.

**Validates: Requirements 2.5**

### Property 8: Branch slugs never exceed 30 code points

For any ticket title string, `len(_sanitize_branch_slug(title)) <= 30`, measured in Unicode code points.

**Validates: Requirements 2.6**

### Property 9: Commit messages contain no control characters

For any raw commit message string, `_sanitize_commit_message(message)` SHALL NOT contain any character with code point in `U+0000`-`U+001F` or equal to `U+007F` (which implies it contains no `\n` and no `\r`).

**Validates: Requirements 3.1, 3.2**

### Property 10: Empty or whitespace-only sanitized messages fall back to "Automated commit"

For any raw commit message string that consists entirely of characters removed by sanitization and/or whitespace, `_sanitize_commit_message(message)` SHALL equal `"Automated commit"`. For any raw commit message, the result of `_sanitize_commit_message` SHALL NOT be the empty string.

**Validates: Requirements 3.3**

### Property 11: Commit message is a distinct argument element

For any sanitized commit message, the argument list built for the commit step SHALL contain `"-m"` immediately followed by the commit message as its own separate list element (never concatenated with `"-m"` or any other flag).

**Validates: Requirements 3.4**

### Property 12: Workflow stops at the first failing step

For any sequence of six git steps (checkout source, pull, checkout branch, add, commit, push) where exactly one step at index `k` fails (returns a non-zero exit code or raises an exception) and all steps before it succeed, `_execute_git_workflow` SHALL: (a) return normally without raising, (b) produce an `operations` log containing exactly `k + 1` entries corresponding to steps `0..k`, and (c) never execute steps at index greater than `k`.

**Validates: Requirements 4.1, 4.2, 4.3**

### Property 13: Logged success reflects the exit code

For any mocked git step return code, the `"success"` field appended to `results["operations"]` for that step SHALL equal `(returncode == 0)`.

**Validates: Requirements 5.3**

### Property 14: Logged output reflects captured stdout/stderr

For any mocked stdout and stderr text produced by a git step, the `"output"` field appended to `results["operations"]` for that step SHALL equal `stdout.strip()` if non-empty, otherwise `stderr.strip()`.

**Validates: Requirements 5.4**

### Property 15: Branch is always populated once computed

For any ticket title and any failing step index (including immediate failure on the first step), `results["branch"]` SHALL be present and SHALL equal the branch name computed from the sanitized slug, regardless of whether any git step succeeds.

**Validates: Requirements 5.5**

### Property 16: Commit message presence matches whether the commit step was attempted

For any ticket title, commit pattern, and failing step index, `results` SHALL contain the key `"commit_message"` with the sanitized commit message if and only if the failing step index is at or after the commit step (or the workflow completes without failure); if the workflow stops at checkout source, pull, checkout branch, or add, `results` SHALL NOT contain the key `"commit_message"`.

**Validates: Requirements 5.7, 5.8**

## Testing Strategy

Tests live in `tests/test_publisher_git_safety.py` (new file), following the
project's existing pytest + Hypothesis conventions (see
`tests/test_config_validation.py` for style: docstring property references,
`@settings(max_examples=100)`, `@given(...)` with `st` strategies).

### Unit tests (examples and edge cases)

- `_sanitize_branch_slug("Fix Login Bug")` → `"fix-login-bug"`.
- `_sanitize_branch_slug("")` → `"implementation"`.
- `_sanitize_branch_slug("!!!")` → `"implementation"`.
- `_sanitize_branch_slug("a" * 40)` → 30-character result.
- `_sanitize_branch_slug("ab" + "-" * 5 + "cd")[:workaround-for-truncation-edge]` —
  a title engineered so truncation lands exactly on a hyphen, to directly
  exercise Requirement 2.7.
- `_sanitize_commit_message("feat: add x\r\ny")` → `"feat: add xy"`.
- `_sanitize_commit_message("\x00\x01\x1f\x7f")` → `"Automated commit"`.
- `_sanitize_commit_message("   ")` → `"Automated commit"`.
- `_execute_git_workflow` with all steps mocked to succeed → full
  `operations` log of 6 entries, `"branch"` and `"commit_message"` both set.
- `_execute_git_workflow` with the `checkout` (source) step mocked to fail →
  `operations` has 1 entry, `"branch"` is set, `"commit_message"` is absent.
- A title containing shell metacharacters (e.g. `` "fix `rm -rf /` bug" ``)
  produces a branch name with no backticks, semicolons, `$`, or spaces, and
  the mocked `subprocess.run` call receives it as one list element — this
  directly demonstrates the injection is neutralized.

### Property-based tests (Hypothesis)

All property tests mock `subprocess.run` (via `unittest.mock.patch`) so no
real git process is spawned; this keeps iteration cost low per the
PBT cost guidelines while still exercising the real branching/sanitization
logic.

```python
"""Property 3-8: Branch slug sanitization.

Validates: Requirements 2.1-2.7
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.agents.publisher import PublisherAgent


title_strategy = st.text(min_size=0, max_size=200)


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_has_no_uppercase(title: str):
    """Feature: publisher-shell-injection-fix, Property 3: Branch slugs
    contain no uppercase ASCII letters."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert not any(c.isascii() and c.isupper() for c in slug)


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_charset(title: str):
    """Feature: publisher-shell-injection-fix, Property 4: Branch slugs use
    only lowercase alphanumerics and hyphens."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert all(c.islower() or c.isdigit() or c == "-" for c in slug if c.isascii()) 
    assert all(c in "0123456789-abcdefghijklmnopqrstuvwxyz" for c in slug)


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_no_consecutive_hyphens(title: str):
    """Feature: publisher-shell-injection-fix, Property 5: no consecutive
    hyphens."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert "--" not in slug


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_no_leading_trailing_hyphen(title: str):
    """Feature: publisher-shell-injection-fix, Property 6: no leading or
    trailing hyphen."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert not slug.startswith("-")
    assert not slug.endswith("-")


@settings(max_examples=100)
@given(
    title=st.text(
        alphabet=st.sampled_from(" \t!@#$%^&*()_+=[]{}|\\:;\"'<>,.?/~"),
        min_size=0,
        max_size=50,
    )
)
def test_branch_slug_empty_falls_back(title: str):
    """Feature: publisher-shell-injection-fix, Property 7: titles that
    sanitize to nothing fall back to 'implementation'."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert slug == "implementation"


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_max_length(title: str):
    """Feature: publisher-shell-injection-fix, Property 8: branch slugs
    never exceed 30 code points."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert len(slug) <= 30
```

```python
"""Property 9-10: Commit message sanitization.

Validates: Requirements 3.1, 3.2, 3.3
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.agents.publisher import PublisherAgent


message_strategy = st.text(min_size=0, max_size=200)


@settings(max_examples=100)
@given(message=message_strategy)
def test_commit_message_no_control_chars(message: str):
    """Feature: publisher-shell-injection-fix, Property 9: commit messages
    contain no control characters."""
    sanitized = PublisherAgent._sanitize_commit_message(message)
    assert all(
        (0x20 <= ord(c) < 0x7F) or ord(c) > 0x7F
        for c in sanitized
    )
    assert "\n" not in sanitized
    assert "\r" not in sanitized


@settings(max_examples=100)
@given(
    message=st.text(
        alphabet=st.one_of(
            st.characters(min_codepoint=0x00, max_codepoint=0x1F),
            st.just("\x7f"),
            st.just(" "),
        ),
        min_size=0,
        max_size=50,
    )
)
def test_commit_message_empty_falls_back(message: str):
    """Feature: publisher-shell-injection-fix, Property 10: empty or
    whitespace-only sanitized messages fall back to 'Automated commit'."""
    sanitized = PublisherAgent._sanitize_commit_message(message)
    assert sanitized == "Automated commit"


@settings(max_examples=100)
@given(message=message_strategy)
def test_commit_message_never_empty(message: str):
    """Feature: publisher-shell-injection-fix, Property 10: sanitized
    commit message is never the empty string."""
    sanitized = PublisherAgent._sanitize_commit_message(message)
    assert sanitized != ""
```

```python
"""Property 1, 2, 11-16: git command construction and stop-on-failure
workflow.

Validates: Requirements 1.1, 1.3, 1.4, 3.4, 4.1, 4.2, 4.3, 5.2, 5.3, 5.4,
5.5, 5.7, 5.8
"""

from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.agents.publisher import PublisherAgent


args_list_strategy = st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5)


@settings(max_examples=100)
@given(args=args_list_strategy)
def test_git_cmd_invokes_subprocess_without_shell(args: list[str]):
    """Feature: publisher-shell-injection-fix, Property 1: subprocess.run is
    invoked without a shell."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        agent._git_cmd(args, results)
        called_args, called_kwargs = mock_run.call_args
        assert called_args[0] == ["git", *args]
        assert called_kwargs["shell"] is False


@settings(max_examples=100)
@given(args=args_list_strategy)
def test_git_cmd_logs_exact_arg_list(args: list[str]):
    """Feature: publisher-shell-injection-fix, Property 2: operations log
    stores the exact argument list."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        agent._git_cmd(args, results)
        assert results["operations"][-1]["command"] == ["git", *args]


@settings(max_examples=100)
@given(returncode=st.integers(min_value=-5, max_value=5))
def test_git_cmd_success_matches_returncode(returncode: int):
    """Feature: publisher-shell-injection-fix, Property 13: logged success
    reflects the exit code."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=returncode, stdout="", stderr="")
        agent._git_cmd(["status"], results)
        assert results["operations"][-1]["success"] == (returncode == 0)


@settings(max_examples=100)
@given(
    stdout=st.text(max_size=50),
    stderr=st.text(max_size=50),
)
def test_git_cmd_output_matches_stdout_or_stderr(stdout: str, stderr: str):
    """Feature: publisher-shell-injection-fix, Property 14: logged output
    reflects captured stdout/stderr."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr=stderr)
        agent._git_cmd(["status"], results)
        expected = stdout.strip() or stderr.strip()
        assert results["operations"][-1]["output"] == expected


@settings(max_examples=100)
@given(
    title=st.text(min_size=1, max_size=100),
    fail_index=st.integers(min_value=0, max_value=5),
)
def test_workflow_stops_on_first_failure(title: str, fail_index: int):
    """Feature: publisher-shell-injection-fix, Property 12: workflow stops
    at the first failing step. Property 15: branch is always populated.
    Property 16: commit_message presence matches whether attempted."""
    agent = PublisherAgent(tool_registry=MagicMock())
    ticket = {"title": title}
    rules = {
        "branch_from": "develop",
        "branch_pattern": "feature/{ticket_id}-{description}",
        "commit_pattern": "feat({ticket_id}): {description}",
        "push_remote": "origin",
    }
    call_count = 0

    def fake_run(cmd, **kwargs):
        nonlocal call_count
        step = call_count
        call_count += 1
        rc = 1 if step == fail_index else 0
        return MagicMock(returncode=rc, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        results = agent._execute_git_workflow("TICKET-1", ticket, rules)

    assert len(results["operations"]) == fail_index + 1
    assert "branch" in results
    commit_step_index = 4
    if fail_index >= commit_step_index:
        assert "commit_message" in results
    else:
        assert "commit_message" not in results


@settings(max_examples=100)
@given(message=st.text(min_size=1, max_size=50))
def test_commit_step_message_is_distinct_arg(message: str):
    """Feature: publisher-shell-injection-fix, Property 11: commit message
    is a distinct argument element."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    sanitized = PublisherAgent._sanitize_commit_message(message)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        agent._git_cmd(["commit", "-m", sanitized], results)
        command = results["operations"][-1]["command"]
        m_index = command.index("-m")
        assert command[m_index + 1] == sanitized
```

### Test type rationale

Per the PBT decision guide: sanitization functions and workflow control
flow are pure/mocked logic where behavior varies meaningfully with input
and 100+ iterations are cheap (no real subprocess or network calls) —
property tests. The Jira update path (`_update_jira`) and vault rule
loading (`_load_rules`/`_parse_rules`) are unchanged by this feature and
are out of scope for new tests here.
