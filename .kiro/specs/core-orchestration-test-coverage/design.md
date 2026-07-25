# Design Document

## Overview

This is a **test-coverage-only** feature. No production code in `autopilot/` changes. The
deliverable is a set of new pytest test modules (plus one addition to an existing test file)
that exercise the retry loop and verdict logic in `engine.py`, the graph wiring in
`graph_builder.py`, `retry_policy.py`'s classification/backoff math, five agents
(`TesterAgent`, `PlannerAgent`, `ContextBuilderAgent`, `DocumentationAgent`, `ReviewerAgent`),
and the DI wiring in `bootstrap.py`.

Every test uses `unittest.mock.MagicMock` (or hand-written fake classes, matching the existing
`_FakeRegistry`/`_FakeSerializer` style seen in `tests/test_state_merge.py`) for collaborators.
No test invokes a real subprocess, a real LLM/OpenCode call, a real Jira/Obsidian HTTP call, or
`time.sleep` for its real duration. `LangGraph`'s compiled `StateGraph` is inspected structurally
(via `compiled_graph.get_graph()`) rather than executed end-to-end with `.invoke()`, except where
the requirement explicitly asks for "the returned object ... exposing an `invoke` callable"
(a structural check, not a real execution).

## Architecture

No architectural change. This section maps each requirement to its target module and new test
file, following the one-test-file-per-component-under-test convention already used in `tests/`
(e.g. `test_run_record.py` ↔ `run_record.py`, `test_ledger.py` ↔ `ledger.py`).

| Requirement | Module under test | New test file |
|---|---|---|
| 1, 2 | `autopilot/application/orchestrator/engine.py` | `tests/test_engine_retry.py` |
| 3 | `autopilot/application/orchestrator/graph_builder.py` | `tests/test_graph_builder.py` |
| 4 | `autopilot/application/orchestrator/retry_policy.py` | `tests/test_retry_policy.py` |
| 5 | `autopilot/infrastructure/agents/tester.py` | `tests/test_tester_agent.py` |
| 6 | `autopilot/infrastructure/agents/planner.py` | `tests/test_planner_agent.py` |
| 7 | `autopilot/infrastructure/agents/context_builder.py` | `tests/test_context_builder_agent.py` |
| 8 | `autopilot/infrastructure/agents/documentation.py` | `tests/test_documentation_agent.py` |
| 9 | `autopilot/infrastructure/agents/reviewer.py` | new test function appended to `tests/test_execution_evidence_and_persistence_fix.py`* |
| 10 | `autopilot/infrastructure/bootstrap.py` | `tests/test_bootstrap.py` |

\* Requirement 9 is a single stub-confirmation check. Rather than create a one-test file, it is
appended as `test_reviewer_agent_execute_always_raises_not_implemented_error` to
`tests/test_execution_evidence_and_persistence_fix.py`, which already contains agent-level tests
in the same "infrastructure agents, mocked collaborators" spirit. (If reviewers prefer a
dedicated file, a `tests/test_reviewer_agent.py` with the same single test is an equally valid,
zero-risk alternative — noted here as an implementation choice, not a requirement.)

Each new test file is self-contained: it imports only the module(s) it targets plus
`unittest.mock`, `hypothesis`, and `pytest`, matching the import style of existing files like
`tests/test_execution_evidence_and_persistence_fix.py` and `tests/test_state_merge.py`.

## Components and Interfaces

### 1. `tests/test_engine_retry.py`

Covers Requirement 1 (retry loop in `create_agent_node`) and Requirement 2 (`execute()` verdict
logic).

**Fakes/mocks used:**

- `_FakeRegistry`, `_FakeSerializer`, `_FakeLogger`, `_FakeConfig` — same minimal fake pattern as
  `test_state_merge.py`, reused/duplicated locally (kept file-local so each test file stays
  independently runnable, matching the existing convention where `test_state_merge.py` and
  `test_execution_evidence_and_persistence_fix.py` each define their own copies).
- A `MagicMock` agent registered on a `MagicMock` `agent_registry` whose `.get(name)` returns it.
  The agent exposes `input_schema = {}` (or a small dict) and `name`/`description` properties are
  irrelevant to the node function, so a bare `MagicMock(input_schema={}, execute=MagicMock(...))`
  suffices.
- `agent.execute` is configured with `side_effect` — a list of exceptions followed by a success
  dict, or an exception repeated `itertools.repeat(exc)`, or a single exception — to drive the
  three retry scenarios (non-retryable / exhausted / success-after-N-failures).
- `RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)` is used **unmocked** for
  most tests since it is pure and fast; `RetryPolicy.classify` is monkey-patched only in the tests
  that need to force a specific classification independent of exception type (e.g. to test the
  delay-value wiring in isolation). Requirement 1.7 fixes `max_retries=3` for every test in this
  requirement so expected counts (`4` total attempts, `3` sleep calls) are concrete.
- `time.sleep` is patched via `@patch("autopilot.application.orchestrator.engine.time.sleep")`
  (patching the name as imported into `engine.py`, not the global `time` module) so no test
  actually waits. The mock's `call_args_list` is asserted against the exact delays
  `RetryPolicy.get_delay(0)`, `get_delay(1)`, ... to satisfy Requirement 1.4.
- For the `execute()` verdict tests (Requirement 2), a `MagicMock()` graph is built with
  `graph.invoke.return_value = {...}` or `graph.invoke.side_effect = SomeException(...)`. A
  `MagicMock()` `run_record_store` is passed to the engine constructor, and a real
  `RunRecord()` instance (not mocked — it's a plain dataclass) is passed to `execute()` so its
  post-call field values (`status`, `verdict`, `tests_executed`, `modified_files`, ...) can be
  asserted directly, mirroring how `test_run_record.py` exercises the real dataclass.

**Key test functions (illustrative names):**

```python
def test_non_retryable_exception_raises_after_single_attempt(): ...
def test_retryable_exception_exhausts_all_attempts_then_raises(): ...
def test_retryable_exception_then_success_returns_output(): ...
def test_sleep_called_with_get_delay_of_current_attempt(): ...
def test_exhausted_retries_persists_error_record_with_attempt_count_four(): ...
def test_non_retryable_persists_error_record_with_attempt_count_one(): ...

def test_execute_no_errors_no_test_evidence_marks_pass(): ...
def test_execute_all_test_result_evidence_passing_marks_pass_with_counts(): ...
def test_execute_some_test_result_evidence_failing_marks_fail_with_counts(): ...
def test_execute_errors_present_marks_status_failed(): ...
def test_execute_invoke_raises_marks_failed_and_reraises(): ...
def test_execute_saves_run_record_exactly_once_on_success_and_on_exception(): ...
def test_execute_without_run_record_returns_result_and_skips_store(): ...
def test_execute_copies_modified_files_into_run_record(): ...
```

### 2. `tests/test_graph_builder.py`

Covers Requirement 3.

**Mocking / inspection strategy:**

- The `engine` collaborator passed to `GraphBuilder(engine=...)` is a `MagicMock()`. Its
  `create_agent_node` method is configured with `side_effect=lambda agent_name: (lambda state: state)`
  so every node added to the real `StateGraph` is a trivial, valid callable — this lets
  `graph.compile()` (the **real**, unmocked LangGraph `StateGraph`/`compile()`) succeed without
  ever calling `.invoke()`. Only the *engine* is mocked; `StateGraph` itself is used for real
  because LangGraph's own compilation/validation is what gives us a trustworthy structural graph
  to inspect, and it has no external side effects (no network, no subprocess, no sleep).
- **Call-count assertions** (3.1, 3.4, 3.6) inspect `engine.create_agent_node.call_args_list`
  directly — e.g. `assert engine.create_agent_node.call_count == len(NODE_AGENT_MAP)` and
  `assert {c.args[0] for c in engine.create_agent_node.call_args_list} == set(NODE_AGENT_MAP.values())`.
- **Structural inspection** (3.2, 3.3, 3.5) uses the compiled graph's own introspection API:
  `compiled = builder.build_work_graph(); rendered = compiled.get_graph()`. `rendered.nodes` is a
  dict keyed by node name (including the synthetic `__start__`/`__end__`), and `rendered.edges` is
  a list of `Edge(source, target, data, conditional)` namedtuples. Tests assert:
  - `hasattr(compiled, "invoke")` and `callable(compiled.invoke)` for 3.2.
  - Plain edges exist for `context_builder→planner`, `planner→code_executor`,
    `code_executor→tester` (each as `Edge(source=a, target=b, conditional=False)` present in
    `rendered.edges`), for 3.3.
  - Three conditional edges originate at `tester`: one to `publisher`, one to `code_executor`, one
    to `__end__`, each with `conditional=True`, for 3.3 and 3.5.
  - Plain edges `publisher→documentation` and `documentation→__end__`, for 3.3.
  - This avoids depending on `add_conditional_edges`'s internal branch-key strings (`"pass"` /
    `"retry"` / `"pause"`) which are not guaranteed to be exposed identically by `get_graph()`
    across LangGraph versions — instead it asserts on the *reachable target set*, which is stable.
- 3.6 (`build_resume_graph` with an invalid node) asserts `pytest.raises(ValueError)` and then
  `engine.create_agent_node.assert_not_called()`.
- 3.7–3.11 (`_route_after_test`) call `builder._route_after_test(state)` directly with hand-built
  state dicts — no graph or engine involvement needed since it's a pure function of `state`.

**Example of the introspection helper shared across these tests:**

```python
def _edge_targets(rendered_graph, source: str, conditional: bool | None = None) -> set[str]:
    """Return the set of target node names reachable from `source`."""
    return {
        e.target for e in rendered_graph.edges
        if e.source == source and (conditional is None or e.conditional == conditional)
    }
```

### 3. `tests/test_retry_policy.py`

Covers Requirement 4. Pure unit/property tests against `RetryPolicy` — no mocking needed since
the class under test has no I/O collaborators.

- 4.1/4.2: `@given(exc_type=st.sampled_from(sorted(RetryPolicy.RETRYABLE_EXCEPTIONS, key=str)))`
  builds `exc_type("boom")` and asserts `policy.classify(exc) == ErrorType.RETRYABLE` (and the
  symmetric case for `NON_RETRYABLE_EXCEPTIONS`).
- 4.3: a small set of locally-defined "arbitrary" exception classes not present in either set
  (e.g. dynamically created via `type("RandomError", (Exception,), {})`, generated with
  `st.integers()` seeding a name suffix to get variety) — `classify` must return
  `ErrorType.NON_RETRYABLE`.
- 4.4: for each retryable base type, a dynamically created subclass
  (`type("Sub", (base,), {})`) instance must classify as `RETRYABLE`.
- 4.5: `@given(attempt=st.integers(0, 2), pair=st.sampled_from([(2.0, 2.0), (5.0, 3.0)]))` builds
  `RetryPolicy(base_delay=pair[0], backoff_multiplier=pair[1])` and asserts
  `policy.get_delay(attempt) == pair[0] * pair[1] ** attempt`. This test is written generally
  enough (parameterizing over both given pairs, generated via `st.sampled_from`, plus optionally a
  broader `st.floats` range for extra confidence) that it also subsumes any narrower example-based
  version of the same check.
- 4.6: a single non-Hypothesis assertion,
  `assert not (RetryPolicy.RETRYABLE_EXCEPTIONS & RetryPolicy.NON_RETRYABLE_EXCEPTIONS)`.

### 4. `tests/test_tester_agent.py`

Covers Requirement 5. Uses `tmp_path`/`monkeypatch.chdir(tmp_path)` (pytest's built-in fixtures,
already used elsewhere in the suite, e.g. `test_integration_cli.py`'s `tmp_path` usage) to control
`Path.cwd()` deterministically per test, since `TesterAgent._detect_test_config` reads from the
current working directory.

**Mocking strategy:**

- `subprocess.run` is patched at `autopilot.infrastructure.agents.tester.subprocess.run` (module-
  qualified, per the module's `import subprocess` statement) via `@patch(...)` or
  `monkeypatch.setattr`. Its `return_value` is a `MagicMock(returncode=0, stdout="...", stderr="")`
  for the passing case, or `returncode=<nonzero>` for the failing case; `side_effect` is set to
  `subprocess.TimeoutExpired(cmd=..., timeout=180)` or `FileNotFoundError(...)` for 5.4/5.7.
- Filesystem fixtures are created directly under `tmp_path`/`monkeypatch.chdir`:
  - 5.1: an empty directory (no marker files).
  - 5.2/5.3: `(tmp_path / "pyproject.toml").write_text("...")`.
  - 5.5: `(tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest --ci"}}))`.
  - 5.6: `(tmp_path / "Makefile").write_text("test:\n\tpytest\n")`.
- `TesterAgent(tool_registry=MagicMock())` is constructed per test (the tool registry is unused by
  `TesterAgent` internals directly touched here, but the constructor requires it).
- 5.3 asserts `pytest.raises(TestFailureError, match=str(exit_code))` (or checks
  `str(exit_code) in str(exc_info.value)`), generated with
  `@given(exit_code=st.integers(min_value=1, max_value=255))` to cover Requirement 5.3's
  "for any exit code" property framing.
- 5.4/5.7 call `agent._run_tests(test_config)` directly (bypassing detection) and assert
  `result == {"success": False, "exit_code": -1, "output": ...}` (checking the two required keys
  precisely, allowing `output` to vary).

### 5. `tests/test_planner_agent.py`

Covers Requirement 6.

**Mocking strategy:**

- `tool_registry = MagicMock()`; `tool_registry.get.return_value` is a `MagicMock()` "opencode"
  tool whose `.execute(prompt=...)` returns `ToolResult(success=True, data={"result": text})` or
  `ToolResult(success=False, data=None, error="...")` — using the real `ToolResult` dataclass
  (it's a plain value object, safe/cheap to construct for precise `.success`/`.data`/`.error`
  attribute access, avoiding `MagicMock` attribute-typo foot-guns).
- For 6.2 ("no opencode tool registered"), `tool_registry.get.side_effect = KeyError("opencode")`.
- `knowledge_engine = MagicMock()`; `knowledge_engine.find_similar.return_value = [...]` a list of
  real `Experience(...)` instances (again, a plain dataclass — cheap and precise) for 6.4/6.7, or
  `find_similar.side_effect = RuntimeError("down")` for 6.5.
- Numbered-line response text is generated with a Hypothesis strategy that builds N synthetic
  "steps" (`st.lists(st.text(...), min_size=1, max_size=8)`) and joins them as
  `f"{i+1}. {desc}"` lines, feeding the constructed string into
  `opencode.execute.return_value = ToolResult(success=True, data={"result": joined_text})`. The
  property then asserts `len(plan["steps"]) == len(descriptions)` and that each step's `agent`
  field is `"Code_Executor"`.
- 6.6 generates response text guaranteed to contain **no** line matching `^\d+\.`, by generating
  free text and asserting/filtering (or simply prefixing every line with a non-digit token) to
  keep the property's precondition intact.
- The "prompt contains PAST EXPERIENCES" checks (6.4/6.7) capture the prompt via
  `opencode.execute.call_args.kwargs["prompt"]` after calling `agent.execute(...)`.

### 6. `tests/test_context_builder_agent.py`

Covers Requirement 7.

**Mocking strategy:**

- `tool_registry = MagicMock()` with `tool_registry.get` routed by name:
  `tool_registry.get.side_effect = lambda name: {"jira": jira_mock, "obsidian": obsidian_mock}[name]`,
  or `side_effect=KeyError(...)` for the "not registered" cases (7.3).
- `jira_mock.execute.return_value = ToolResult(success=True, data={...})` /
  `ToolResult(success=False, error="...")`; same pattern for `obsidian_mock.execute`.
- Ticket dicts and note lists are generated with small Hypothesis dict/list strategies
  (`st.dictionaries`, `st.lists(st.text(...))`) to vary title/labels/description/comments/notes
  content per Requirements 7.4/7.7/7.8's "for any" framing, while keeping the dict shapes close to
  what `ContextBuilderAgent` actually reads (`id`, `title`, `description`, `comments`, `labels`).
- 7.1 uses `@given(ticket=st.one_of(st.just({}), st.fixed_dictionaries({"id": st.just("")})))`
  plus arbitrary extra keys, asserting the Jira mock's `.execute` is never called
  (`jira_mock.execute.assert_not_called()`).

### 7. `tests/test_documentation_agent.py`

Covers Requirement 8. No external tools are actually invoked by `DocumentationAgent.execute`
(the `tool_registry` constructor arg is accepted but unused in the current implementation), so
`DocumentationAgent(tool_registry=MagicMock())` is constructed once and reused.

- Plans/files/evidence are generated via Hypothesis strategies producing lists of small dicts
  (`{"step": i, "description": text}`, file path strings, `{"description": text, "data": {"status": status}}`
  with `status` drawn from `st.sampled_from(["passed", "failed", "skipped"])` to guarantee
  "differing status values" per 8.1) and the resulting `documentation_draft` string is asserted to
  contain every generated description/path/status via substring checks (`in`).
- 8.2/8.3 hold `modified_files=[]` / `evidence=[]` fixed while other fields vary, asserting the
  literal substrings `"No files tracked"` / `"No test evidence recorded"`.
- 8.4 asserts `metadata["documentation_status"] == "generated"` across all generated inputs.

### 8. Requirement 9 addition (ReviewerAgent stub)

A single test appended to `tests/test_execution_evidence_and_persistence_fix.py`:

```python
def test_reviewer_agent_execute_always_raises_not_implemented_error():
    agent = ReviewerAgent(tool_registry=MagicMock())
    with pytest.raises(NotImplementedError):
        agent.execute({"modified_files": [], "context": {}})
```

(with an added `from autopilot.infrastructure.agents.reviewer import ReviewerAgent` import at the
top of that file). A Hypothesis-driven variant is layered on top with
`@given(state=st.dictionaries(st.text(), st.one_of(st.none(), st.text(), st.integers())))` to
exercise the "for any input state" framing without depending on any particular shape, since the
stub ignores its argument entirely.

### 9. `tests/test_bootstrap.py`

Covers Requirement 10.

**Fixture file:** a Test_Suite-owned YAML fixture is written to a `tmp_path`-based location at
test time (not committed as a static file, to avoid an absolute `vault_location`/
`workspace_location` baked into a repo file colliding with the executing machine's filesystem):

```python
@pytest.fixture
def bootstrap_config_path(tmp_path):
    config_file = tmp_path / "bootstrap_test_config.yaml"
    config_file.write_text(
        f"""
vault_location: "{tmp_path / 'vault'}"
workspace_location: "{tmp_path / 'workspace'}"
available_mcps: []
llm_model: "anthropic/claude-sonnet-4-20250514"
llm_provider: "anthropic"
timeout_seconds: 60
max_retries: 3
base_delay: 2.0
backoff_multiplier: 2.0
verbosity: quiet
""".strip()
    )
    return str(config_file)
```

- No mocking of `create_application`'s internals is needed or desired — this is a smoke test of
  real DI wiring. All collaborators it constructs (`JiraTool`, `ObsidianTool`, `OpenCodeTool`,
  `RunRecordStore`, `Ledger`, `LedgerCommitter`, etc.) are cheap, side-effect-free at construction
  time (no network calls or subprocess calls happen in `__init__`), so building them for real is
  safe and is exactly what a wiring smoke test should do.
- 10.1/10.2/10.3 call `create_application(bootstrap_config_path)` once and assert every named
  attribute (`config`, `engine`, `work_command`, `resume_command`, `config_command`,
  `knowledge_engine`, `experience_builder`, `run_record_store`, `ledger`, `ledger_committer`) is
  not `None`, and `isinstance(app.engine, OrchestrationEngine)`.
- 10.4 calls `create_application(str(tmp_path / "does_not_exist.yaml"))` and asserts
  `pytest.raises(SystemExit)` (matching `YAMLConfigLoader.load`'s documented behavior of creating
  a default config and raising `SystemExit(1)` when the path doesn't exist).

## Data Models

No new data models. Tests consume the existing `RunRecord`, `ErrorRecord`, `ErrorType`,
`ToolResult`, `Experience`, `Config` dataclasses/enums as-is, matching the pattern already
established in `test_run_record.py` and `test_serialization_roundtrip.py` of constructing real
instances of these lightweight value types rather than mocking them.

## Error Handling

Not applicable in the traditional sense — this feature adds tests, not runtime error handling.
Test-level "error handling" concerns are:

- Every test that expects an exception uses `pytest.raises(...)` (never a bare `try`/`except`)
  so an unexpected passing case fails loudly instead of being silently skipped.
- Tests that assert *no* exception is raised (e.g. Requirement 2.7, 6.5) call the function under
  test directly inside the test body without a surrounding `try`/`except` — if it raises, pytest
  reports the failure naturally; no explicit `pytest.fail()` wrapping is needed.
- Mocked `subprocess.run` and `time.sleep` patches are always scoped with `@patch`/`monkeypatch`
  (auto-undone at test teardown) rather than manual monkey-patching, to prevent leakage between
  tests in the same session.

## Testing Strategy

**Dual approach**, per file:

- **Property tests** (Hypothesis, `max_examples=100`, matching the project convention in
  `test_state_merge.py`/`test_publisher_git_safety.py`) cover the requirements classified
  `PROPERTY` in the prework below — retry counts under varying failure patterns, verdict
  determination under varying evidence/error shapes, `classify`/`get_delay` over the exception
  sets and backoff formula, agent behaviors that vary meaningfully with ticket/plan/evidence
  content.
- **Example-based unit tests** cover requirements classified `EXAMPLE`/`EDGE_CASE` — the fixed
  6-node graph topology (structural, not input-varying), specific file-detection fixture
  combinations (`package.json` + jest, `Makefile` + `test:`), the two subprocess-exception edge
  cases, and the bootstrap smoke test (DI wiring is single-shape, not a function of varying
  input).
- Every property test function includes a docstring with
  `**Feature: core-orchestration-test-coverage, Property N: <title>**` and
  `**Validates: Requirements X.Y**`, following the `test_state_merge.py` docstring convention.
- Running `python3 -m pytest tests/test_engine_retry.py tests/test_graph_builder.py tests/test_retry_policy.py tests/test_tester_agent.py tests/test_planner_agent.py tests/test_context_builder_agent.py tests/test_documentation_agent.py tests/test_bootstrap.py -v`
  must pass with zero real subprocess/network/sleep activity; the full suite
  (`python3 -m pytest`) must continue passing (currently 176+ tests) with no regressions.

### Correctness Pre-work (Acceptance Criteria Testing Prework)

1.1 Non-retryable exception on first attempt
  Thoughts: This is about the general behavior of the retry loop for any agent/exception combination classified non-retryable. We can generate an agent whose execute always raises a non-retryable exception and assert execute is called once, exception re-raised, sleep never called. This holds across many agent names/exception types.
  Testable: yes - property

1.2 Retryable exception on every attempt exhausts retries
  Thoughts: General behavior regardless of which retryable exception/agent. Assert execute called max_retries+1 times then re-raises.
  Testable: yes - property

1.3 Retryable exception then success
  Thoughts: General behavior parameterized by number of failing attempts (0..max_retries) before success. Assert output returned, invocation/sleep counts equal failures.
  Testable: yes - property

1.4 Delay passed to sleep equals get_delay(N)
  Thoughts: For any attempt index N during retries, the sleep call before attempt N+1 uses the exact delay RetryPolicy.get_delay(N) computes.
  Testable: yes - property

1.5 Exhausted retries records attempt_count=4 and exception_class
  Thoughts: Specific scenario with fixed numbers (max_retries=3).
  Testable: yes - example

1.6 Non-retryable on first attempt records attempt_count=1
  Thoughts: Specific scenario for the non-retryable persisted error path with fixed numbers.
  Testable: yes - example

1.7 Fixed max_retries=3 configuration requirement
  Thoughts: Test configuration convention, not an independently observable behavior.
  Testable: no

2.1 No errors, no test evidence -> PASS
  Thoughts: For any graph result lacking errors/test evidence, verdict defaults to PASS.
  Testable: yes - property

2.2 All test_result evidence passing -> PASS with correct counts
  Thoughts: Property over varying evidence list content, all entries passing.
  Testable: yes - property

2.3 Some test_result evidence failing -> FAIL with correct counts
  Thoughts: Property over varying evidence lists with mixed pass/fail entries.
  Testable: yes - property

2.4 Errors present -> status failed regardless of test evidence
  Thoughts: Property over varying errors/evidence combinations.
  Testable: yes - property

2.5 Exception from invoke -> failed status, message, save-before-raise, propagation
  Thoughts: Property over varying exception types/messages.
  Testable: yes - property

2.6 Store.save invoked exactly once on both success and exception paths
  Thoughts: Property combining both paths, varying results/exceptions.
  Testable: yes - property

2.7 No RunRecord passed -> no store call, result returned unchanged
  Thoughts: Property over varying graph results with the run_record arg omitted.
  Testable: yes - property

2.8 modified_files list copied into RunRecord.modified_files
  Thoughts: Property over varying file lists.
  Testable: yes - property

3.1 build_work_graph calls create_agent_node once per NODE_AGENT_MAP entry
  Thoughts: Fixed 6-entry mapping; concrete structural check via mock call list.
  Testable: yes - example

3.2 build_work_graph returns compiled graph exposing invoke
  Thoughts: Structural fact about one specific call.
  Testable: yes - example

3.3 build_work_graph node/edge structure matches fixed topology
  Thoughts: Structural fact about the fixed graph topology, verified via get_graph().
  Testable: yes - example

3.4 build_resume_graph invoked with three resume_from values, create_agent_node called once per map entry
  Thoughts: Holds across all valid resume_from values, not just the three named ones — generalizable property over WORK_GRAPH_NODES.
  Testable: yes - property

3.5 build_resume_graph(resume_from="tester") has same conditional branching as work graph
  Thoughts: Specific structural check for one resume_from value.
  Testable: yes - example

3.6 build_resume_graph with invalid node name raises ValueError, engine not called
  Thoughts: Holds for any string not in WORK_GRAPH_NODES — generalizable property.
  Testable: yes - property

3.7 _route_after_test empty errors -> "pass"
  Thoughts: Property over varying accompanying state fields with errors=[].
  Testable: yes - property

3.8 _route_after_test last error retryable -> "retry"
  Thoughts: Property over varying error list shapes whose last entry is retryable.
  Testable: yes - property

3.9 _route_after_test last error non_retryable -> "pause"
  Thoughts: Property over varying error lists whose last entry is non_retryable.
  Testable: yes - property

3.10 _route_after_test last error_type other/absent -> "pause"
  Thoughts: Property over varying error_type values including absence.
  Testable: yes - property

3.11 _route_after_test only last entry matters
  Thoughts: Metamorphic property complementing 3.8-3.10, generated via multi-entry error lists within the same tests.
  Testable: yes - property

4.1 classify() on RETRYABLE_EXCEPTIONS instance -> RETRYABLE
  Thoughts: Property generated from the known exception set.
  Testable: yes - property

4.2 classify() on NON_RETRYABLE_EXCEPTIONS instance -> NON_RETRYABLE
  Thoughts: Property generated from the known exception set.
  Testable: yes - property

4.3 classify() on unknown exception type -> NON_RETRYABLE (default)
  Thoughts: Property over generated arbitrary exception classes.
  Testable: yes - property

4.4 classify() on subclass of retryable type -> RETRYABLE
  Thoughts: Property over generated subclasses (isinstance semantics).
  Testable: yes - property

4.5 get_delay() formula for attempts 0,1,2 across two (base,multiplier) pairs
  Thoughts: Direct formula-verification property, generalizable beyond the two given pairs.
  Testable: yes - property

4.6 No exception type in both RETRYABLE_EXCEPTIONS and NON_RETRYABLE_EXCEPTIONS
  Thoughts: Static invariant about two class-level sets; single-assertion check.
  Testable: yes - example

5.1 No test framework detected -> skipped, no subprocess.run call
  Thoughts: Fixed absence condition in an empty temp directory.
  Testable: yes - example

5.2 pyproject.toml present + subprocess zero exit -> passed status, no exception
  Thoughts: Specific scenario with one config file and one mocked outcome.
  Testable: yes - example

5.3 pyproject.toml present + subprocess non-zero exit -> raises TestFailureError with exit code in message
  Thoughts: Generalizes across varying non-zero exit codes.
  Testable: yes - property

5.4 subprocess.run raises TimeoutExpired -> success False, exit_code -1
  Thoughts: Deterministic single code path regardless of input variation.
  Testable: yes - edge-case

5.5 package.json with jest test script -> framework jest, command "npm test"
  Thoughts: Specific fixture-based scenario for one config shape.
  Testable: yes - example

5.6 Makefile with test: line -> framework make, command "make test"
  Thoughts: Specific fixture scenario.
  Testable: yes - example

5.7 subprocess.run raises FileNotFoundError -> success False, exit_code -1
  Thoughts: Deterministic single code path.
  Testable: yes - edge-case

6.1 OpenCode success with numbered lines -> one step per numbered line, agent Code_Executor
  Thoughts: Property generating varying numbers/content of numbered lines.
  Testable: yes - property

6.2 No opencode tool registered -> fallback plan with exactly one step, no fallback_reason
  Thoughts: Property over varying ticket titles.
  Testable: yes - property

6.3 OpenCode failed result -> fallback plan with one step, fallback_reason equals tool's error
  Thoughts: Property over varying error messages.
  Testable: yes - property

6.4 Knowledge engine find_similar returns experiences -> prompt contains "PAST EXPERIENCES"
  Thoughts: Property over varying experience lists/content.
  Testable: yes - property

6.5 Knowledge engine find_similar raises exception -> execute still succeeds without raising
  Thoughts: Property over varying exception types/messages.
  Testable: yes - property

6.6 OpenCode success with no numbered lines -> single step whose description equals full response text
  Thoughts: Property over varying non-numbered response text.
  Testable: yes - property

6.7 Knowledge engine find_similar returns empty list -> prompt excludes "PAST EXPERIENCES"
  Thoughts: Complementary property to 6.4.
  Testable: yes - property

7.1 Ticket dict missing/empty id -> unchanged ticket, context error, empty sources, no Jira call
  Thoughts: Property over varying ticket dict shapes lacking a usable id.
  Testable: yes - property

7.2 Jira tool success -> fetched ticket data returned unchanged as "ticket"
  Thoughts: Property over varying ticket data shapes.
  Testable: yes - property

7.3 Jira tool not registered -> _fetch_ticket returns dict with original id and error key
  Thoughts: Property over varying ticket_id values.
  Testable: yes - property

7.4 Obsidian tool success with notes -> sources contains obsidian_notes entry with correct count
  Thoughts: Property over varying notes lists.
  Testable: yes - property

7.5 Obsidian tool failure -> _search_obsidian returns empty list
  Thoughts: Property over varying failure reasons.
  Testable: yes - property

7.6 Jira tool registered but fails -> dict with id, empty fields, error equal to tool's error
  Thoughts: Property over varying error messages.
  Testable: yes - property

7.7 Ticket has non-empty description and comments -> sources contains both entries
  Thoughts: Property over varying description/comments content.
  Testable: yes - property

7.8 Ticket has no title and no labels -> obsidian not called, related_notes empty
  Thoughts: Property over varying remaining ticket fields.
  Testable: yes - property

8.1 Plan/files/evidence with required sizes -> draft contains all details
  Thoughts: Property over varying generated plans/files/evidence meeting size/diversity constraints.
  Testable: yes - property

8.2 Empty modified_files -> draft contains "No files tracked"
  Thoughts: Property over varying other inputs held constant on the empty-list condition.
  Testable: yes - property

8.3 Empty evidence -> draft contains "No test evidence recorded"
  Thoughts: Symmetric property over varying other inputs.
  Testable: yes - property

8.4 Successful execute -> metadata.documentation_status == "generated"
  Thoughts: Property over varying inputs, status always "generated" on success.
  Testable: yes - property

9.1 ReviewerAgent.execute raises NotImplementedError for any input state
  Thoughts: Property over varying state inputs; implementation ignores input entirely.
  Testable: yes - property

10.1-10.3 create_application with valid fixture -> non-None attributes, correct type, no exception
  Thoughts: One-time DI-wiring smoke check against a single fixture config; doesn't vary meaningfully with input.
  Testable: yes - example

10.4 create_application with nonexistent config path -> SystemExit
  Thoughts: Specific error-path scenario for a missing file.
  Testable: yes - example

### Property Reflection

Reviewing the PROPERTY-classified criteria above for redundancy before finalizing the
Correctness Properties section:

- **1.1/1.2/1.3** are three branches of one underlying retry-loop behavior (stop-on-non-retryable,
  exhaust-on-always-retryable, succeed-after-N-retryable-failures). They are kept as three
  properties because each asserts a genuinely different outcome (re-raise-immediately vs.
  re-raise-after-max vs. return-success), not because they're testing different code — merging
  them into one property would require a compound conditional assertion that obscures which
  invariant broke on failure. Kept separate.
- **1.4** (delay-value wiring) is independent of 1.1-1.3's pass/fail outcome — it constrains *how*
  retries wait, not *whether* they occur. Kept separate.
- **1.5/1.6** are EXAMPLE-classified (fixed max_retries=3 concrete numbers), not folded into the
  1.1-1.3 properties, but they do validate a detail (attempt_count, exception_class in the
  persisted error) that 1.1-1.3 don't check. Kept as dedicated example tests, not promoted to
  properties, since the requirement text pins concrete numbers rather than "for all N".
- **2.1/2.2/2.3** together fully define the verdict decision table (no tests → PASS, all pass →
  PASS, some fail → FAIL). These are kept as three properties rather than one because each has a
  distinct precondition (test evidence shape) and a distinct expected verdict — collapsing them
  would hide which branch of the decision table regressed. However, 2.2 and 2.3 share nearly
  identical setup (a list of test_result evidence entries) and could be expressed as a *single*
  parameterized property: "for any evidence list, verdict is PASS iff every entry passes, and
  tests_executed/tests_passed/tests_failed always match the evidence counts." This consolidation
  is adopted below as **Property 5** (replacing separate 2.2/2.3 properties) since it strictly
  subsumes both criteria and is a stronger single statement.
- **2.4** is independent of 2.1/2.2/2.3 (errors present overrides verdict entirely) — kept
  separate as **Property 6**.
- **2.5/2.6** overlap: 2.6 ("save invoked exactly once on both paths") is a strict superset of
  half of 2.5's assertions (the save-before-raise part). Consolidated into a single **Property 7**
  that states both the failure-path state transition *and* the exactly-once save guarantee across
  both normal-return and exception paths, since testing them separately would duplicate the same
  mock setup for no added confidence.
- **2.7** and **2.8** are independent, narrow behaviors (store not touched when no RunRecord;
  modified_files copied through) — kept as their own properties (**Property 8**, **Property 9**).
- **3.4** and **3.6** are independent (valid resume points vs. invalid resume points) — kept
  separate.
- **3.7/3.8/3.9/3.10** define one routing decision table keyed by `error_type` of the last error
  entry. Per the same reasoning as 2.2/2.3, these are consolidated into a single **Property 12**:
  "for any non-empty errors list, `_route_after_test` returns `retry` iff the last entry's
  `error_type == "retryable"`, else `pause`; and for an empty list it returns `pass`." This
  strictly subsumes 3.7, 3.9, and 3.10 (all "not retryable" cases collapse to the `else` branch)
  while still distinctly stating the `pass`/`retry`/`pause` trichotomy.
- **3.11** ("only the last entry matters") is a metamorphic strengthening of Property 12 rather
  than a separate property: it is validated by generating multi-entry error lists *within*
  Property 12's own test (varying earlier entries' `error_type` independently of the last one), so
  it is folded into Property 12's test implementation and not given a separate property number.
- **4.1/4.2** are symmetric halves of one classification table; kept as two properties
  (**Property 13**, **Property 14**) since they reference two distinct, disjoint sets, but they
  are adjacent and simple enough that a reviewer could also merge them — not merged here to keep
  each property's counterexample immediately attributable to the right set.
- **4.3** (unknown type → NON_RETRYABLE) and **4.2** (explicit NON_RETRYABLE_EXCEPTIONS member →
  NON_RETRYABLE) are related but distinct: 4.3 tests the *default* branch, 4.2 tests explicit
  membership. Both matter because a bug could make the default branch wrong while explicit
  membership still works (or vice versa). Kept separate (**Property 15**).
- **4.4** is a strengthening of 4.1 (subclass instead of exact type) — kept separate
  (**Property 16**) since `isinstance` vs. exact-type-equality is exactly the kind of bug this
  distinct property is designed to catch; 4.1 alone would not catch a hypothetical switch to
  exact-type comparison.
- **6.1** and **6.6** are complementary halves of `_parse_plan`'s branching (numbered-lines path
  vs. no-numbered-lines path) — kept separate (**Property 20**, **Property 21**) since they
  exercise genuinely different parsing branches with different expected shapes.
- **6.4** and **6.7** are complementary (non-empty vs. empty `find_similar` result) and are
  consolidated into a single **Property 22**: "for any list of past experiences returned by
  `find_similar`, the prompt contains `PAST EXPERIENCES` iff the list is non-empty" — this is
  strictly stronger than testing the two halves separately.
- **7.4/7.5** (Obsidian success-with-notes vs. failure) are kept as separate properties
  (**Property 26**, **Property 27**) since they exercise different tool outcomes with materially
  different assertions (sources content vs. empty-list return from a different method).
- **8.1/8.2/8.3/8.4** are kept as four properties rather than consolidated, because although they
  all examine `documentation_draft`/`documentation_status`, each isolates a distinct input
  condition (rich input, empty files, empty evidence, general success) whose corresponding
  assertion is a different substring/field check — consolidating would require an if/elif chain
  inside one test that reduces failure-localization value more than it saves setup code.

No further merges reduce the property count without losing failure-localization clarity, so the
Correctness Properties section below reflects the consolidations described above (2.2+2.3 → one
property, 2.5+2.6 → one property, 3.7/3.9/3.10 → one property with 3.11 folded in as a
strengthening within the same test, 6.4+6.7 → one property) while keeping all other
PROPERTY-classified criteria as distinct properties.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of
a system — a formal statement about what the system should do. Properties serve as the bridge
between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Non-retryable exceptions stop the retry loop immediately

For any agent whose `execute` raises an exception classified `NON_RETRYABLE` on its first
invocation, the Agent_Node SHALL call `execute` exactly once, re-raise the original exception
instance, and never call `sleep`.

**Validates: Requirements 1.1**

### Property 2: Retryable exceptions on every attempt exhaust the configured retry budget

For any agent whose `execute` always raises an exception classified `RETRYABLE`, with
`max_retries` fixed at 3, the Agent_Node SHALL call `execute` exactly 4 times before re-raising
the original exception.

**Validates: Requirements 1.2**

### Property 3: A retryable failure followed by success returns the successful output

For any sequence of 0 to `max_retries` retryable-exception failures followed by a successful
`execute` call, the Agent_Node SHALL return the successful output without re-raising, and the
number of `execute` invocations and the number of `sleep` calls SHALL each equal the number of
failed attempts that preceded the success.

**Validates: Requirements 1.3**

### Property 4: Retry backoff delay matches `RetryPolicy.get_delay` for the current attempt

For any zero-indexed attempt N at which a retryable exception triggers a retry, the value passed
to `sleep` before attempt N+1 SHALL equal `RetryPolicy.get_delay(N)`.

**Validates: Requirements 1.4**

### Property 5: Verdict reflects the pass/fail composition of test-result evidence

For any graph result whose `evidence` list contains zero or more entries of `type ==
"test_result"`, the RunRecord's `verdict` SHALL be `"PASS"` if every such entry's `result` starts
with `"PASS"` (case-insensitive) — including the case of zero such entries — and `"FAIL"`
otherwise; and `tests_executed`, `tests_passed`, and `tests_failed` SHALL always equal,
respectively, the total count of test-result entries, the count whose `result` starts with
`"PASS"`, and the remainder.

**Validates: Requirements 2.1, 2.2, 2.3**

### Property 6: A non-empty errors list always marks the run failed

For any graph result containing one or more entries in its `errors` list, regardless of any
test-result evidence also present, the RunRecord's `status` SHALL be `"failed"`.

**Validates: Requirements 2.4**

### Property 7: The run-record store is saved exactly once, and reflects failure on exception

For any graph whose `invoke` either returns normally or raises an exception, when a RunRecord and
a run-record store are both supplied to `execute()`, the store's `save` method SHALL be invoked
exactly once with the final RunRecord instance; and if `invoke` raised an exception, the
RunRecord's `status` SHALL be `"failed"` with a failure message equal to the exception's string
representation, the store's `save` SHALL be invoked before the exception propagates, and the
exception SHALL propagate out of `execute()` unchanged.

**Validates: Requirements 2.5, 2.6**

### Property 8: Omitting the RunRecord skips all run-record store interaction

For any graph result, when `execute()` is called without a `run_record` argument, the graph
result SHALL be returned unchanged and no method on any run-record store SHALL be invoked.

**Validates: Requirements 2.7**

### Property 9: Modified files pass through unchanged into the RunRecord

For any list of file paths present in a graph result's `modified_files` field, the RunRecord's
`modified_files` field after `execute()` SHALL equal that same list.

**Validates: Requirements 2.8**

### Property 10: Every graph-builder call wires exactly one node per registered agent

For any call to `build_work_graph`, and for any call to `build_resume_graph` with a valid
`resume_from` value drawn from `WORK_GRAPH_NODES`, `create_agent_node` SHALL be invoked exactly
once for each entry in `NODE_AGENT_MAP`, with the corresponding agent name as its argument.

**Validates: Requirements 3.1, 3.4**

### Property 11: An invalid resume node is rejected without touching the engine

For any string not present in `WORK_GRAPH_NODES`, calling `build_resume_graph` with that string as
`resume_from` SHALL raise `ValueError` and SHALL NOT invoke `create_agent_node`.

**Validates: Requirements 3.6**

### Property 12: Post-test routing is a total function of the last error's type

For any graph state, `_route_after_test` SHALL return `"pass"` if the state's `errors` list is
empty; otherwise it SHALL return `"retry"` if the last entry in `errors` has `error_type ==
"retryable"`, and `"pause"` for any other value of the last entry's `error_type` (including the
key being absent) — and this outcome SHALL depend only on the last entry, regardless of the
`error_type` values of any earlier entries in the list.

**Validates: Requirements 3.7, 3.8, 3.9, 3.10, 3.11**

### Property 13: Every listed retryable exception type classifies as retryable

For any exception type in `RetryPolicy.RETRYABLE_EXCEPTIONS`, an instance of that type SHALL
classify as `ErrorType.RETRYABLE`.

**Validates: Requirements 4.1**

### Property 14: Every listed non-retryable exception type classifies as non-retryable

For any exception type in `RetryPolicy.NON_RETRYABLE_EXCEPTIONS`, an instance of that type SHALL
classify as `ErrorType.NON_RETRYABLE`.

**Validates: Requirements 4.2**

### Property 15: Unrecognized exception types default to non-retryable

For any exception type present in neither `RETRYABLE_EXCEPTIONS` nor `NON_RETRYABLE_EXCEPTIONS`,
an instance of that type SHALL classify as `ErrorType.NON_RETRYABLE`.

**Validates: Requirements 4.3**

### Property 16: Subclasses of retryable exceptions inherit retryable classification

For any subclass of a type listed in `RETRYABLE_EXCEPTIONS`, an instance of that subclass SHALL
classify as `ErrorType.RETRYABLE`.

**Validates: Requirements 4.4**

### Property 17: Backoff delay follows the exponential formula for any attempt and configuration

For any non-negative attempt number and any `(base_delay, backoff_multiplier)` configuration,
`get_delay(attempt)` SHALL equal `base_delay * backoff_multiplier ** attempt`.

**Validates: Requirements 4.5**

### Property 18: Non-zero test-runner exit codes surface as a matching failure message

For any non-zero exit code returned by the mocked test-runner subprocess when a `pyproject.toml`
is present, `TesterAgent.execute` SHALL raise `TestFailureError` whose message contains the
decimal string representation of that exit code.

**Validates: Requirements 5.3**

### Property 19: Numbered-line OpenCode responses parse into one step per line

For any OpenCode response text composed of one or more lines each beginning with a digit followed
by a period, `PlannerAgent._parse_plan` SHALL produce a `steps` list with exactly one entry per
such line, each entry having a `step` number, a `description`, and `agent == "Code_Executor"`.

**Validates: Requirements 6.1**

### Property 20: Responses with no numbered lines collapse to a single whole-text step

For any OpenCode response text containing no line beginning with a digit followed by a period,
`PlannerAgent._parse_plan` SHALL produce a `steps` list with exactly one entry whose `description`
equals the full response text.

**Validates: Requirements 6.6**

### Property 21: Missing or failing OpenCode tool always yields a single-step fallback plan

For any ticket, when the `"opencode"` tool is not registered, `PlannerAgent.execute` SHALL return
a fallback plan with exactly one step derived from the ticket title and no `fallback_reason` key;
and for any error string reported by a failed OpenCode result, `PlannerAgent.execute` SHALL return
a fallback plan with exactly one step whose `fallback_reason` equals that error string.

**Validates: Requirements 6.2, 6.3**

### Property 22: The prompt mentions past experiences if and only if the knowledge engine found any

For any list of experiences returned by the knowledge engine's `find_similar`, the prompt passed
to the OpenCode tool SHALL contain the text `"PAST EXPERIENCES"` if and only if that list is
non-empty.

**Validates: Requirements 6.4, 6.7**

### Property 23: Knowledge-engine failures never prevent plan generation

For any exception raised by the knowledge engine's `find_similar`, `PlannerAgent.execute` SHALL
still invoke the OpenCode tool and return a plan without raising.

**Validates: Requirements 6.5**

### Property 24: A missing or empty ticket ID short-circuits context building without contacting Jira

For any ticket dict that has no `"id"` field or whose `"id"` field is an empty string,
`ContextBuilderAgent.execute` SHALL return the original ticket dict unchanged as `"ticket"`, a
context dict containing an `"error"` key with an empty `"sources"` list, and SHALL NOT invoke the
Jira tool.

**Validates: Requirements 7.1**

### Property 25: Jira tool outcomes propagate faithfully into `_fetch_ticket`'s return value

For any ticket ID, a successful Jira result's data SHALL be returned unchanged as `execute`'s
`"ticket"` output; a Jira tool not registered SHALL cause `_fetch_ticket` to return a dict
containing that same ticket ID and an `"error"` key; and a registered-but-failing Jira tool SHALL
cause `_fetch_ticket` to return a dict containing that ticket ID, empty `title`/`description`/
`status` fields, and an `"error"` key equal to the tool's reported error string.

**Validates: Requirements 7.2, 7.3, 7.6**

### Property 26: Obsidian notes are reflected in context sources with an accurate count

For any non-empty list of notes returned by a successful Obsidian tool call, the resulting
context's `"sources"` list SHALL contain an entry with `type == "obsidian_notes"` and `count`
equal to the number of notes returned.

**Validates: Requirements 7.4**

### Property 27: A failing Obsidian search always yields an empty note list

For any failed Obsidian tool result, `_search_obsidian` SHALL return an empty list.

**Validates: Requirements 7.5**

### Property 28: Non-empty description and comments each contribute a distinct source entry

For any fetched ticket data with non-empty `"description"` and non-empty `"comments"` fields, the
resulting context's `"sources"` list SHALL contain an entry with `type == "jira_description"` and
an entry with `type == "jira_comments"`.

**Validates: Requirements 7.7**

### Property 29: Absence of title and labels skips the Obsidian search entirely

For any fetched ticket data with no title and no labels, `_search_obsidian` SHALL NOT be invoked,
and the resulting context's `"related_notes"` list SHALL be empty.

**Validates: Requirements 7.8**

### Property 30: The documentation draft contains every step, file, and evidence item supplied

For any plan with at least two steps, any `modified_files` list with at least two paths, and any
`evidence` list with at least two items of differing status values, `DocumentationAgent.execute`'s
`metadata.documentation_draft` SHALL contain each step's description, each file path, and each
evidence item's description together with its status value.

**Validates: Requirements 8.1**

### Property 31: Empty file or evidence lists always produce their respective placeholder text

For any plan and evidence, when `modified_files` is empty, the documentation draft SHALL contain
`"No files tracked"`; and for any plan and modified files, when `evidence` is empty, the
documentation draft SHALL contain `"No test evidence recorded"`.

**Validates: Requirements 8.2, 8.3**

### Property 32: Successful documentation generation always reports status "generated"

For any plan, modified files, and evidence, a successful call to `DocumentationAgent.execute`
SHALL return `metadata.documentation_status == "generated"`.

**Validates: Requirements 8.4**

### Property 33: ReviewerAgent unconditionally raises NotImplementedError

For any input state, calling `ReviewerAgent.execute` SHALL raise `NotImplementedError`.

**Validates: Requirements 9.1**

## Testing Strategy Requirements

**Unit tests** (example-based, one or a handful of concrete scenarios each) are used for:

- The fixed 6-node work-graph topology and its exact edge structure (Requirement 3.2, 3.3, 3.5) —
  structural facts about one specific, non-varying construction.
- `build_work_graph`'s exact `create_agent_node` call arguments (Requirement 3.1) — a fixed
  6-entry mapping.
- The 1.5/1.6 concrete-number persisted-error-state checks (`attempt_count == 4`/`== 1`,
  `exception_class`) with `max_retries` pinned at 3.
- `TesterAgent` file-detection fixture combinations (5.1, 5.2, 5.5, 5.6) and the two subprocess
  exception edge cases (5.4, 5.7) — deterministic single-path behaviors tied to specific fixture
  file contents.
- The `RETRYABLE_EXCEPTIONS`/`NON_RETRYABLE_EXCEPTIONS` disjointness check (4.6) — a static,
  input-independent invariant.
- The bootstrap smoke test (10.1-10.4) — DI wiring correctness for one representative valid
  config and one missing-file config; wiring behavior does not vary meaningfully across inputs.

**Property tests** (Hypothesis, `@settings(max_examples=100)`, matching existing project
convention) are used for all 33 properties listed above, covering the retry loop's invocation/
timing counts, the RunRecord verdict decision table, graph-builder wiring generality across valid/
invalid resume points, the post-test routing decision table, `RetryPolicy`'s classification and
backoff formula, and the input-varying behaviors of `TesterAgent`, `PlannerAgent`,
`ContextBuilderAgent`, `DocumentationAgent`, and `ReviewerAgent`.

Each property test tag follows the format:
**Feature: core-orchestration-test-coverage, Property {number}: {property title}**
