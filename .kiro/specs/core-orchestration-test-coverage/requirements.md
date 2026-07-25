# Requirements Document

## Introduction

The core orchestration engine (`engine.py`, `graph_builder.py`, `retry_policy.py`) and several agents (`TesterAgent`, `PlannerAgent`, `ContextBuilderAgent`, `DocumentationAgent`, `ReviewerAgent`) currently have no or partial automated test coverage. The dependency-injection bootstrap (`create_application()`) also lacks a smoke test. This feature adds unit-level test coverage for these components using mocked collaborators (no live subprocess execution, no live LLM calls, no full `graph.invoke()` integration run), so that regressions in retry behavior, run-verdict logic, graph routing, agent execution paths, and DI wiring are caught automatically.

## Glossary

- **Test_Suite**: The pytest-based automated test code added or modified by this feature.
- **OrchestrationEngine**: The class in `autopilot/application/orchestrator/engine.py` responsible for building agent node functions and executing compiled graphs.
- **GraphBuilder**: The class in `autopilot/application/orchestrator/graph_builder.py` responsible for constructing LangGraph `StateGraph` instances for the work and resume workflows.
- **RetryPolicy**: The class in `autopilot/application/orchestrator/retry_policy.py` responsible for classifying exceptions and computing retry delays.
- **TesterAgent**: The class in `autopilot/infrastructure/agents/tester.py` responsible for detecting the test framework and running the test suite via `subprocess.run`.
- **PlannerAgent**: The class in `autopilot/infrastructure/agents/planner.py` responsible for producing an implementation plan from a ticket and context.
- **ContextBuilderAgent**: The class in `autopilot/infrastructure/agents/context_builder.py` responsible for assembling ticket and knowledge-source context.
- **DocumentationAgent**: The class in `autopilot/infrastructure/agents/documentation.py` responsible for generating a markdown work summary.
- **ReviewerAgent**: The class in `autopilot/infrastructure/agents/reviewer.py`, a stub implementation that always raises `NotImplementedError`.
- **Bootstrap_Module**: The `create_application` function in `autopilot/infrastructure/bootstrap.py` responsible for dependency-injection wiring.
- **RunRecord**: The dataclass entity in `autopilot/domain/entities/run_record.py` that tracks a workflow execution's status, verdict, and metrics.
- **Agent_Node**: The callable produced by `OrchestrationEngine.create_agent_node(agent_name)`.
- **Mocked_Collaborator**: A test double (e.g., `unittest.mock.MagicMock`) substituted for a real dependency such as an agent, tool registry, subprocess call, or LLM client.

## Requirements

### Requirement 1: Agent_Node retry-loop coverage

**User Story:** As a maintainer, I want the Agent_Node retry loop covered by tests, so that changes to retry counting, backoff invocation, and exception propagation are caught before release.

#### Acceptance Criteria

1. WHEN a Mocked_Collaborator agent's `execute` raises an exception classified as non-retryable, THE Test_Suite SHALL verify that the Agent_Node invokes `execute` exactly once, re-raises the original exception, and invokes no sleep call.
2. WHEN a Mocked_Collaborator agent's `execute` raises an exception classified as retryable on every attempt, THE Test_Suite SHALL verify that the Agent_Node invokes `execute` exactly `max_retries + 1` times before re-raising the original exception.
3. WHEN a Mocked_Collaborator agent's `execute` raises a retryable exception on one or more attempts and succeeds on a subsequent attempt, THE Test_Suite SHALL verify that the Agent_Node returns the successful output without re-raising, and that the number of `execute` invocations and sleep calls matches the number of failed attempts before success.
4. WHEN the Agent_Node retries after a retryable exception on zero-indexed attempt N, THE Test_Suite SHALL verify that the delay value returned by `RetryPolicy.get_delay(N)` is passed to the sleep call made before attempt N+1.
5. IF all retry attempts are exhausted for a retryable exception with a fixed `max_retries` value of 3, THEN THE Test_Suite SHALL verify that the persisted error state records an `attempt_count` equal to 4 and an `exception_class` equal to the raised exception's type name.
6. IF a non-retryable exception is raised on the first attempt, THEN THE Test_Suite SHALL verify that the persisted error state records an `attempt_count` equal to 1, an `exception_class` equal to the raised exception's type name, and that no further attempts are made.
7. THE Test_Suite SHALL use a fixed `max_retries` value of 3 for RetryPolicy configuration across the test scenarios in this requirement, so that expected invocation counts are concrete and unambiguous.

### Requirement 2: OrchestrationEngine.execute() RunRecord verdict coverage

**User Story:** As a maintainer, I want the RunRecord verdict logic in `OrchestrationEngine.execute()` covered by tests, so that verdict determination (PASS/FAIL) stays correct as evidence and error handling evolve.

#### Acceptance Criteria

1. WHEN a Mocked_Collaborator graph's `invoke` returns a result with no errors and no test-result evidence, THE Test_Suite SHALL verify that the RunRecord's `status` is `"completed"` and `verdict` is `"PASS"`.
2. WHEN a Mocked_Collaborator graph's `invoke` returns a result whose `evidence` list contains entries with `type` equal to `"test_result"` and a `result` field starting with `"PASS"` (case-insensitive) for every entry, THE Test_Suite SHALL verify that the RunRecord's `status` is `"completed"`, `verdict` is `"PASS"`, and `tests_executed`/`tests_passed` equal the number of such entries.
3. WHEN a Mocked_Collaborator graph's `invoke` returns a result whose `evidence` list contains entries with `type` equal to `"test_result"` where at least one entry's `result` field does not start with `"PASS"` (case-insensitive), THE Test_Suite SHALL verify that the RunRecord's `status` is `"completed"`, `verdict` is `"FAIL"`, and `tests_executed`/`tests_passed`/`tests_failed` match the evidence counts.
4. WHEN a Mocked_Collaborator graph's `invoke` returns a result containing one or more entries in the `errors` list, THE Test_Suite SHALL verify that the RunRecord's `status` is `"failed"` regardless of any test-result evidence present, without asserting a `verdict` value for this path.
5. IF a Mocked_Collaborator graph's `invoke` raises an exception, THEN THE Test_Suite SHALL verify that the RunRecord's `status` is `"failed"` with a failure message equal to the exception's string representation, that the run-record store's save method is invoked before the exception propagates, and that the exception propagates out of `execute()`.
6. WHEN `execute()` completes (whether by returning normally or by the exception path in criterion 5) and a run-record store is configured, THE Test_Suite SHALL verify that the store's save method is invoked exactly once with the updated RunRecord instance.
7. WHEN `execute()` is called without a RunRecord argument, THE Test_Suite SHALL verify that the graph result is returned without error and without invoking any run-record store.
8. WHEN a Mocked_Collaborator graph's `invoke` returns a result containing a `modified_files` list, THE Test_Suite SHALL verify that the RunRecord's `modified_files` field equals that list.

### Requirement 3: GraphBuilder unit-level coverage

**User Story:** As a maintainer, I want `build_work_graph`, `build_resume_graph`, and `_route_after_test` covered by unit tests with a mocked engine, so that graph wiring and conditional routing regressions are caught without running a full graph execution.

#### Acceptance Criteria

1. WHEN `build_work_graph` is called with a Mocked_Collaborator engine, THE Test_Suite SHALL verify that `create_agent_node` is invoked once for each entry in `NODE_AGENT_MAP` with the corresponding agent name.
2. WHEN `build_work_graph` is called, THE Test_Suite SHALL verify that the returned object is a compiled graph exposing an `invoke` callable.
3. WHEN `build_work_graph` is called, THE Test_Suite SHALL verify that the compiled graph's node and edge structure connects the nodes in the sequence `context_builder` → `planner` → `code_executor` → `tester`, and that `tester` is connected via conditional branching to `publisher`, to `code_executor`, and to a terminal end state, and that `publisher` connects to `documentation` which connects to a terminal end state.
4. WHEN `build_resume_graph` is called separately with `resume_from` equal to `"context_builder"`, `"tester"`, and `"documentation"`, THE Test_Suite SHALL verify that for each call, `create_agent_node` is invoked once for each entry in `NODE_AGENT_MAP`.
5. WHEN `build_resume_graph` is called with `resume_from` equal to `"tester"`, THE Test_Suite SHALL verify that the compiled graph's edge structure includes conditional branching from `tester` to `publisher`, to `code_executor`, and to a terminal end state, matching the branching used in `build_work_graph`.
6. IF `build_resume_graph` is called with a node name not present in `WORK_GRAPH_NODES`, THEN THE Test_Suite SHALL verify that a `ValueError` is raised and that the Mocked_Collaborator engine's `create_agent_node` method is not invoked.
7. WHEN `_route_after_test` is called with a state whose `errors` list is empty, THE Test_Suite SHALL verify that it returns `"pass"`.
8. WHEN `_route_after_test` is called with a state whose last error entry has `error_type` equal to `"retryable"`, THE Test_Suite SHALL verify that it returns `"retry"`.
9. WHEN `_route_after_test` is called with a state whose last error entry has `error_type` equal to `"non_retryable"`, THE Test_Suite SHALL verify that it returns `"pause"`.
10. WHEN `_route_after_test` is called with a state whose last error entry has an `error_type` value other than `"retryable"`, including an entry with the `error_type` key absent, THE Test_Suite SHALL verify that it returns `"pause"` in each case.
11. WHEN `_route_after_test` is called with a state containing multiple error entries where an earlier entry's `error_type` differs from the last entry's `error_type`, THE Test_Suite SHALL verify that the returned routing key matches only what the last entry's `error_type` would produce.

### Requirement 4: RetryPolicy classify() and get_delay() coverage

**User Story:** As a maintainer, I want `RetryPolicy.classify()` and `RetryPolicy.get_delay()` covered by tests, so that error-classification and backoff-timing regressions are caught.

#### Acceptance Criteria

1. WHEN `classify` is called with an instance of any exception type listed in `RETRYABLE_EXCEPTIONS`, THE Test_Suite SHALL verify that it returns `ErrorType.RETRYABLE`.
2. WHEN `classify` is called with an instance of any exception type listed in `NON_RETRYABLE_EXCEPTIONS`, THE Test_Suite SHALL verify that it returns `ErrorType.NON_RETRYABLE`.
3. WHEN `classify` is called with an exception type not present in either set, THE Test_Suite SHALL verify that it returns `ErrorType.NON_RETRYABLE`.
4. WHEN `classify` is called with a subclass instance of a type listed in `RETRYABLE_EXCEPTIONS`, THE Test_Suite SHALL verify that it returns `ErrorType.RETRYABLE`.
5. WHEN `get_delay` is called with attempt numbers 0, 1, and 2 using each of the following `(base_delay, backoff_multiplier)` pairs: `(2.0, 2.0)` and `(5.0, 3.0)`, THE Test_Suite SHALL verify that the returned value for each attempt equals `base_delay * backoff_multiplier ** attempt`.
6. THE Test_Suite SHALL verify that no exception type appears in both `RETRYABLE_EXCEPTIONS` and `NON_RETRYABLE_EXCEPTIONS`.

### Requirement 5: TesterAgent coverage with mocked subprocess execution

**User Story:** As a maintainer, I want TesterAgent covered by tests that mock `subprocess.run`, so that test-framework detection and pass/fail evidence handling are verified without executing real test commands.

#### Acceptance Criteria

1. WHEN no `package.json`, `pyproject.toml`, or `setup.py` is present, and no `Makefile` containing a line with `test:` is present, in the working directory, THE Test_Suite SHALL verify that `execute` returns evidence with `status` equal to `"skipped"` and does not invoke `subprocess.run`.
2. WHEN a `pyproject.toml` is present and the Mocked_Collaborator `subprocess.run` returns a zero exit code, THE Test_Suite SHALL verify that `execute` returns evidence with `status` equal to `"passed"` and does not raise an exception.
3. IF a `pyproject.toml` is present and the Mocked_Collaborator `subprocess.run` returns a non-zero exit code, THEN THE Test_Suite SHALL verify that `execute` raises `TestFailureError` whose message contains the decimal string representation of that exit code.
4. IF the Mocked_Collaborator `subprocess.run` raises `subprocess.TimeoutExpired`, THEN THE Test_Suite SHALL verify that `_run_tests` returns a result with `success` equal to `False` and `exit_code` equal to `-1`.
5. WHEN a `package.json` declaring a `"test"` script containing `"jest"` is present, THE Test_Suite SHALL verify that `_parse_node_test_config` returns a configuration with `framework` equal to `"jest"` and `command` equal to `"npm test"`.
6. WHEN no `package.json`, `pyproject.toml`, or `setup.py` is present, but a `Makefile` containing a line with `test:` is present, THE Test_Suite SHALL verify that `_detect_test_config` returns a configuration with `framework` equal to `"make"` and `command` equal to `"make test"`.
7. IF the Mocked_Collaborator `subprocess.run` raises `FileNotFoundError`, THEN THE Test_Suite SHALL verify that `_run_tests` returns a result with `success` equal to `False` and `exit_code` equal to `-1`.

### Requirement 6: PlannerAgent coverage

**User Story:** As a maintainer, I want PlannerAgent covered by tests that mock the OpenCode tool and knowledge engine, so that plan generation, fallback behavior, and knowledge-engine consultation are verified without calling a real LLM.

#### Acceptance Criteria

1. WHEN the Mocked_Collaborator OpenCode tool returns a successful result whose response text contains lines beginning with a digit followed by a period (e.g. "1.", "2."), THE Test_Suite SHALL verify that `execute` returns a plan whose `steps` list has one entry per such numbered line, each with a `step` number, a `description`, and `agent` equal to `"Code_Executor"`.
2. IF the tool registry does not have an `"opencode"` tool registered, THEN THE Test_Suite SHALL verify that `execute` returns a fallback plan containing exactly one step derived from the ticket title, with no `fallback_reason` key present in the plan.
3. IF the Mocked_Collaborator OpenCode tool returns a failed result, THEN THE Test_Suite SHALL verify that `execute` returns a fallback plan containing exactly one step, whose `fallback_reason` equals the tool's reported error.
4. WHEN a Mocked_Collaborator knowledge engine's `find_similar` returns a non-empty list of experiences, THE Test_Suite SHALL verify that the prompt passed to the OpenCode tool contains the text `"PAST EXPERIENCES"`.
5. IF the Mocked_Collaborator knowledge engine's `find_similar` raises an exception, THEN THE Test_Suite SHALL verify that `execute` still calls the OpenCode tool and returns a plan without raising.
6. WHEN the Mocked_Collaborator OpenCode tool returns a successful result whose response text contains no line beginning with a digit followed by a period, THE Test_Suite SHALL verify that `execute` returns a plan whose `steps` list contains exactly one entry whose `description` equals the full response text.
7. WHEN a Mocked_Collaborator knowledge engine's `find_similar` returns an empty list, THE Test_Suite SHALL verify that the prompt passed to the OpenCode tool does not contain the text `"PAST EXPERIENCES"`.

### Requirement 7: ContextBuilderAgent coverage

**User Story:** As a maintainer, I want ContextBuilderAgent covered by tests that mock the Jira and Obsidian tools, so that context assembly and error fallbacks are verified without calling real external services.

#### Acceptance Criteria

1. IF the input ticket dict has no `"id"` field, or has an `"id"` field equal to an empty string, THEN THE Test_Suite SHALL verify that `execute` returns the original ticket dict unchanged as `"ticket"`, a context dict containing an `"error"` key, an empty `"sources"` list, and does not call the Jira tool.
2. WHEN the Mocked_Collaborator Jira tool returns a successful result, THE Test_Suite SHALL verify that `execute` returns the fetched ticket data unchanged as the `"ticket"` output field.
3. IF the tool registry does not have a `"jira"` tool registered, THEN THE Test_Suite SHALL verify that `_fetch_ticket` returns a dict containing the original ticket ID and an `"error"` key.
4. WHEN the Mocked_Collaborator Obsidian tool returns a successful result with notes, THE Test_Suite SHALL verify that the returned context's `"sources"` list contains an entry with `type` equal to `"obsidian_notes"` and `count` equal to the number of notes returned.
5. IF the Mocked_Collaborator Obsidian tool returns a failed result, THEN THE Test_Suite SHALL verify that `_search_obsidian` returns an empty list.
6. IF the Mocked_Collaborator Jira tool is registered but returns a failed result, THEN THE Test_Suite SHALL verify that `_fetch_ticket` returns a dict containing the original ticket ID, empty `title`/`description`/`status` fields, and an `"error"` key equal to the tool's reported error.
7. WHEN the fetched ticket data contains non-empty `"description"` and non-empty `"comments"` fields, THE Test_Suite SHALL verify that the returned context's `"sources"` list contains an entry with `type` equal to `"jira_description"` and an entry with `type` equal to `"jira_comments"`.
8. WHEN the fetched ticket data has no title and no labels, THE Test_Suite SHALL verify that `_search_obsidian` is not called and the returned context's `"related_notes"` list is empty.

### Requirement 8: DocumentationAgent coverage

**User Story:** As a maintainer, I want DocumentationAgent covered by tests, so that the generated markdown summary reflects plan steps, modified files, and test evidence correctly.

#### Acceptance Criteria

1. WHEN `execute` is called with a plan containing at least two steps, a `modified_files` list containing at least two file paths, and an `evidence` list containing at least two items with differing status values, THE Test_Suite SHALL verify that the returned `metadata.documentation_draft` contains each step's description, each modified file path, and each evidence item's description together with its status value.
2. WHEN `execute` is called with an empty `modified_files` list, THE Test_Suite SHALL verify that the returned `metadata.documentation_draft` contains the text `"No files tracked"`.
3. WHEN `execute` is called with an empty `evidence` list, THE Test_Suite SHALL verify that the returned `metadata.documentation_draft` contains the text `"No test evidence recorded"`.
4. WHEN `execute` completes successfully, THE Test_Suite SHALL verify that the returned dict's `metadata.documentation_status` equals `"generated"`.

### Requirement 9: ReviewerAgent stub-confirmation coverage

**User Story:** As a maintainer, I want a test confirming ReviewerAgent's stub behavior, so that an accidental partial implementation is caught before it silently changes the agent's contract.

#### Acceptance Criteria

1. WHEN `execute` is called on a ReviewerAgent instance with any input state, THE Test_Suite SHALL verify that a `NotImplementedError` is raised.

### Requirement 10: Bootstrap smoke-test coverage

**User Story:** As a maintainer, I want a smoke test for `create_application()`, so that dependency-injection wiring failures are caught immediately rather than surfacing later as CLI errors.

#### Acceptance Criteria

1. WHEN `create_application` is called with the path to a Test_Suite-owned fixture file containing a syntactically valid, complete YAML configuration, THE Test_Suite SHALL verify that the returned `Application` object's `config`, `engine`, `work_command`, `resume_command`, `config_command`, `knowledge_engine`, `experience_builder`, `run_record_store`, `ledger`, and `ledger_committer` attributes are all non-`None`.
2. WHEN `create_application` is called with that fixture file, THE Test_Suite SHALL verify that the returned `Application.engine` is an instance of `OrchestrationEngine`.
3. WHEN `create_application` is called with that fixture file, THE Test_Suite SHALL verify that no exception is raised during dependency wiring.
4. IF `create_application` is called with a configuration path that does not exist on disk, THEN THE Test_Suite SHALL verify that a `SystemExit` is raised.
