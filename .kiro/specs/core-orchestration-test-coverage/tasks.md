# Implementation Plan: core-orchestration-test-coverage

## Overview

This is a test-coverage-only feature: no production code under `autopilot/` changes. The plan is
organized one task group per new (or amended) test file, matching the design's
module-to-test-file mapping. Each group first sets up any shared fakes/fixtures the file needs,
then adds one sub-task per property test (tagged with its Property number from the design's
Correctness Properties section) or example/edge-case test, each annotated with the acceptance
criteria it validates. Checkpoints are placed between file groups so failures are caught close to
the change that introduced them.

Convert the feature design into a series of prompts for a code-generation LLM that will implement
each step with incremental progress. Make sure that each prompt builds on the previous prompts,
and ends with wiring things together. There should be no hanging or orphaned code that isn't
integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing
code.

## Tasks

- [x] 1. Implement `tests/test_engine_retry.py`
  - [x] 1.1 Set up shared fakes and fixed retry configuration
    - Define file-local `_FakeRegistry`, `_FakeSerializer`, `_FakeLogger`, `_FakeConfig` matching
      the pattern in `tests/test_state_merge.py`
    - Build a `MagicMock` agent (with `input_schema = {}`) registered on a mocked
      `agent_registry`, and a `RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)`
      per Requirement 1.7
    - Patch `autopilot.application.orchestrator.engine.time.sleep` for the whole file
    - _Requirements: 1.7_

  - [x] 1.2 Write property test for Property 1: non-retryable exceptions stop the retry loop
    - **Property 1: Non-retryable exceptions stop the retry loop immediately**
    - **Validates: Requirements 1.1**

  - [x] 1.3 Write property test for Property 2: retryable exceptions exhaust the retry budget
    - **Property 2: Retryable exceptions on every attempt exhaust the configured retry budget**
    - **Validates: Requirements 1.2**

  - [x] 1.4 Write property test for Property 3: retryable failure then success returns output
    - **Property 3: A retryable failure followed by success returns the successful output**
    - **Validates: Requirements 1.3**

  - [x] 1.5 Write property test for Property 4: sleep delay matches `RetryPolicy.get_delay`
    - **Property 4: Retry backoff delay matches `RetryPolicy.get_delay` for the current attempt**
    - **Validates: Requirements 1.4**

  - [x] 1.6 Write example test for exhausted-retry persisted error state
    - Fixed `max_retries=3` scenario asserting persisted `attempt_count == 4` and
      `exception_class` equals the raised exception's type name
    - _Requirements: 1.5, 1.7_

  - [x] 1.7 Write example test for non-retryable persisted error state
    - Fixed scenario asserting persisted `attempt_count == 1` and `exception_class` equals the
      raised exception's type name
    - _Requirements: 1.6, 1.7_

  - [x] 1.8 Write property test for Property 5: verdict reflects test-evidence composition
    - **Property 5: Verdict reflects the pass/fail composition of test-result evidence**
    - **Validates: Requirements 2.1, 2.2, 2.3**

  - [x] 1.9 Write property test for Property 6: non-empty errors list always marks the run failed
    - **Property 6: A non-empty errors list always marks the run failed**
    - **Validates: Requirements 2.4**

  - [x] 1.10 Write property test for Property 7: store saved exactly once, failure path recorded
    - **Property 7: The run-record store is saved exactly once, and reflects failure on exception**
    - **Validates: Requirements 2.5, 2.6**

  - [x] 1.11 Write property test for Property 8: omitting the RunRecord skips the store
    - **Property 8: Omitting the RunRecord skips all run-record store interaction**
    - **Validates: Requirements 2.7**

  - [x] 1.12 Write property test for Property 9: modified files pass through unchanged
    - **Property 9: Modified files pass through unchanged into the RunRecord**
    - **Validates: Requirements 2.8**

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement `tests/test_graph_builder.py`
  - [x] 3.1 Set up mocked engine and edge-inspection helper
    - Configure `engine.create_agent_node.side_effect` to return a trivial passthrough callable
      per agent name so the real `StateGraph.compile()` succeeds
    - Add an `_edge_targets(rendered_graph, source, conditional=None)` helper for structural
      assertions against `compiled.get_graph()`
    - _Requirements: 3.1_

  - [x] 3.2 Write example test for `build_work_graph` create_agent_node call counts
    - Assert `create_agent_node` is invoked once per `NODE_AGENT_MAP` entry with the correct agent
      names
    - _Requirements: 3.1_

  - [x] 3.3 Write example test for compiled graph exposing `invoke`
    - Assert the object returned by `build_work_graph` has a callable `invoke` attribute
    - _Requirements: 3.2_

  - [x] 3.4 Write example test for the fixed node/edge topology
    - Assert the plain edges `context_builder→planner`, `planner→code_executor`,
      `code_executor→tester`, `publisher→documentation`, `documentation→__end__`, and the three
      conditional edges from `tester` to `publisher`, `code_executor`, and `__end__`
    - _Requirements: 3.3_

  - [x] 3.5 Write property test for Property 10: create_agent_node wiring across valid graphs
    - **Property 10: Every graph-builder call wires exactly one node per registered agent**
    - **Validates: Requirements 3.1, 3.4**

  - [x] 3.6 Write example test for `build_resume_graph(resume_from="tester")` branching
    - Assert the same conditional-branch target set from `tester` as in the work graph
    - _Requirements: 3.5_

  - [x] 3.7 Write property test for Property 11: invalid resume node rejected without engine use
    - **Property 11: An invalid resume node is rejected without touching the engine**
    - **Validates: Requirements 3.6**

  - [x] 3.8 Write property test for Property 12: post-test routing depends only on the last error
    - **Property 12: Post-test routing is a total function of the last error's type**
    - **Validates: Requirements 3.7, 3.8, 3.9, 3.10, 3.11**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement `tests/test_retry_policy.py`
  - [x] 5.1 Write property test for Property 13: retryable exception types classify retryable
    - **Property 13: Every listed retryable exception type classifies as retryable**
    - **Validates: Requirements 4.1**

  - [x] 5.2 Write property test for Property 14: non-retryable exception types classify correctly
    - **Property 14: Every listed non-retryable exception type classifies as non-retryable**
    - **Validates: Requirements 4.2**

  - [x] 5.3 Write property test for Property 15: unrecognized types default to non-retryable
    - **Property 15: Unrecognized exception types default to non-retryable**
    - **Validates: Requirements 4.3**

  - [x] 5.4 Write property test for Property 16: subclasses of retryable types classify retryable
    - **Property 16: Subclasses of retryable exceptions inherit retryable classification**
    - **Validates: Requirements 4.4**

  - [x] 5.5 Write property test for Property 17: backoff formula holds for any attempt/config
    - **Property 17: Backoff delay follows the exponential formula for any attempt and configuration**
    - **Validates: Requirements 4.5**

  - [x] 5.6 Write example test asserting `RETRYABLE_EXCEPTIONS`/`NON_RETRYABLE_EXCEPTIONS` disjoint
    - Single assertion that the two class-level sets share no exception type
    - _Requirements: 4.6_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement `tests/test_tester_agent.py`
  - [x] 7.1 Set up `tmp_path`/`monkeypatch.chdir` fixtures and `subprocess.run` patch helpers
    - Patch `autopilot.infrastructure.agents.tester.subprocess.run` per test as needed
    - Construct `TesterAgent(tool_registry=MagicMock())` per test
    - _Requirements: 5.1_

  - [x] 7.2 Write example test for no test framework detected
    - Empty working directory; assert evidence `status == "skipped"` and `subprocess.run` is not
      called
    - _Requirements: 5.1_

  - [x] 7.3 Write example test for `pyproject.toml` present with a zero exit code
    - Assert evidence `status == "passed"` and no exception is raised
    - _Requirements: 5.2_

  - [x] 7.4 Write property test for Property 18: non-zero exit codes raise a matching failure
    - **Property 18: Non-zero test-runner exit codes surface as a matching failure message**
    - **Validates: Requirements 5.3**

  - [x] 7.5 Write edge-case test for `subprocess.TimeoutExpired`
    - Assert `_run_tests` returns `success == False` and `exit_code == -1`
    - _Requirements: 5.4_

  - [x] 7.6 Write example test for `package.json` declaring a jest test script
    - Assert `_parse_node_test_config` returns `framework == "jest"` and `command == "npm test"`
    - _Requirements: 5.5_

  - [x] 7.7 Write example test for a `Makefile` containing a `test:` line
    - Assert `_detect_test_config` returns `framework == "make"` and `command == "make test"`
    - _Requirements: 5.6_

  - [x] 7.8 Write edge-case test for `FileNotFoundError` from `subprocess.run`
    - Assert `_run_tests` returns `success == False` and `exit_code == -1`
    - _Requirements: 5.7_

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement `tests/test_planner_agent.py`
  - [x] 9.1 Set up mocked tool registry and knowledge engine fixtures
    - Route `tool_registry.get` to a mocked `"opencode"` tool returning real `ToolResult`
      instances; mock `knowledge_engine.find_similar` returning real `Experience` instances
    - _Requirements: 6.2_

  - [x] 9.2 Write property test for Property 19: numbered-line responses parse one step per line
    - **Property 19: Numbered-line OpenCode responses parse into one step per line**
    - **Validates: Requirements 6.1**

  - [x] 9.3 Write property test for Property 20: non-numbered responses collapse to one step
    - **Property 20: Responses with no numbered lines collapse to a single whole-text step**
    - **Validates: Requirements 6.6**

  - [x] 9.4 Write property test for Property 21: missing/failing opencode tool yields a fallback
    - **Property 21: Missing or failing OpenCode tool always yields a single-step fallback plan**
    - **Validates: Requirements 6.2, 6.3**

  - [x] 9.5 Write property test for Property 22: prompt mentions past experiences iff found
    - **Property 22: The prompt mentions past experiences if and only if the knowledge engine found any**
    - **Validates: Requirements 6.4, 6.7**

  - [x] 9.6 Write property test for Property 23: knowledge-engine failures never block plan generation
    - **Property 23: Knowledge-engine failures never prevent plan generation**
    - **Validates: Requirements 6.5**

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement `tests/test_context_builder_agent.py`
  - [x] 11.1 Set up mocked tool registry routing Jira and Obsidian mocks
    - Route `tool_registry.get` by name to independent Jira/Obsidian `MagicMock` tools returning
      real `ToolResult` instances, or raise `KeyError` for "not registered" scenarios
    - _Requirements: 7.3_

  - [x] 11.2 Write property test for Property 24: missing/empty id short-circuits without Jira
    - **Property 24: A missing or empty ticket ID short-circuits context building without contacting Jira**
    - **Validates: Requirements 7.1**

  - [x] 11.3 Write property test for Property 25: Jira outcomes propagate into `_fetch_ticket`
    - **Property 25: Jira tool outcomes propagate faithfully into `_fetch_ticket`'s return value**
    - **Validates: Requirements 7.2, 7.3, 7.6**

  - [x] 11.4 Write property test for Property 26: Obsidian notes reflected with accurate count
    - **Property 26: Obsidian notes are reflected in context sources with an accurate count**
    - **Validates: Requirements 7.4**

  - [x] 11.5 Write property test for Property 27: failing Obsidian search yields an empty list
    - **Property 27: A failing Obsidian search always yields an empty note list**
    - **Validates: Requirements 7.5**

  - [x] 11.6 Write property test for Property 28: description and comments each add a source entry
    - **Property 28: Non-empty description and comments each contribute a distinct source entry**
    - **Validates: Requirements 7.7**

  - [x] 11.7 Write property test for Property 29: absent title/labels skip the Obsidian search
    - **Property 29: Absence of title and labels skips the Obsidian search entirely**
    - **Validates: Requirements 7.8**

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement `tests/test_documentation_agent.py`
  - [x] 13.1 Set up Hypothesis strategies for plans, modified files, and evidence
    - Build strategies for step dicts, file path strings, and evidence dicts with
      `status` drawn from `st.sampled_from(["passed", "failed", "skipped"])`
    - Construct a single reused `DocumentationAgent(tool_registry=MagicMock())`
    - _Requirements: 8.1_

  - [x] 13.2 Write property test for Property 30: draft contains every step, file, and evidence item
    - **Property 30: The documentation draft contains every step, file, and evidence item supplied**
    - **Validates: Requirements 8.1**

  - [x] 13.3 Write property test for Property 31: empty lists produce placeholder text
    - **Property 31: Empty file or evidence lists always produce their respective placeholder text**
    - **Validates: Requirements 8.2, 8.3**

  - [x] 13.4 Write property test for Property 32: successful generation reports status "generated"
    - **Property 32: Successful documentation generation always reports status "generated"**
    - **Validates: Requirements 8.4**

- [x] 14. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Add ReviewerAgent stub-confirmation test
  - [x] 15.1 Add ReviewerAgent import and property test to `tests/test_execution_evidence_and_persistence_fix.py`
    - Add `from autopilot.infrastructure.agents.reviewer import ReviewerAgent` import
    - **Property 33: ReviewerAgent unconditionally raises NotImplementedError**
    - **Validates: Requirements 9.1**

- [x] 16. Implement `tests/test_bootstrap.py`
  - [x] 16.1 Write `bootstrap_config_path` fixture
    - Generate a `tmp_path`-based syntactically valid, complete YAML configuration file
    - _Requirements: 10.1_

  - [x] 16.2 Write example test for valid-fixture wiring
    - Assert `config`, `engine`, `work_command`, `resume_command`, `config_command`,
      `knowledge_engine`, `experience_builder`, `run_record_store`, `ledger`, and
      `ledger_committer` are all non-`None`, `engine` is an `OrchestrationEngine` instance, and no
      exception is raised
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 16.3 Write example test for a nonexistent configuration path
    - Assert `create_application` raises `SystemExit` when given a path that does not exist on
      disk
    - _Requirements: 10.4_

- [x] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- This is a test-coverage-only feature: every task above adds or modifies test code, and none of
  the sub-tasks are marked optional (`*`) because the tests themselves are this feature's core
  deliverable, not supplementary coverage on top of separate production code changes.
- Each property test sub-task references its Property number and title from the design's
  Correctness Properties section, plus the acceptance criteria it validates, for traceability.
- Checkpoints are placed after each test file's group so a regression or setup mistake in one
  file's fakes/fixtures is caught before moving to the next file.
- Running `python3 -m pytest tests/test_engine_retry.py tests/test_graph_builder.py tests/test_retry_policy.py tests/test_tester_agent.py tests/test_planner_agent.py tests/test_context_builder_agent.py tests/test_documentation_agent.py tests/test_bootstrap.py -v` must pass with zero real subprocess/network/sleep activity, and the full suite (`python3 -m pytest`) must continue passing with no regressions.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1", "5.1", "7.1", "9.1", "11.1", "13.1", "15.1", "16.1"] },
    { "id": 1, "tasks": ["1.2", "3.2", "5.2", "7.2", "9.2", "11.2", "13.2", "16.2"] },
    { "id": 2, "tasks": ["1.3", "3.3", "5.3", "7.3", "9.3", "11.3", "13.3", "16.3"] },
    { "id": 3, "tasks": ["1.4", "3.4", "5.4", "7.4", "9.4", "11.4", "13.4"] },
    { "id": 4, "tasks": ["1.5", "3.5", "5.5", "7.5", "9.5", "11.5"] },
    { "id": 5, "tasks": ["1.6", "3.6", "5.6", "7.6", "9.6", "11.6"] },
    { "id": 6, "tasks": ["1.7", "3.7", "7.7", "11.7"] },
    { "id": 7, "tasks": ["1.8", "3.8", "7.8"] },
    { "id": 8, "tasks": ["1.9"] },
    { "id": 9, "tasks": ["1.10"] },
    { "id": 10, "tasks": ["1.11"] },
    { "id": 11, "tasks": ["1.12"] }
  ]
}
```
