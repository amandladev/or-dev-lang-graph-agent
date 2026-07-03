# Implementation Plan: Autopilot MVP Foundation

## Overview

Build the foundational architecture for the Autopilot developer workflow orchestration system. This MVP establishes the Clean Architecture package structure, domain entities and interfaces, application-layer registries and orchestrator skeleton, infrastructure adapters (serializer, config loader, logger), a basic CLI, an initial LangGraph graph setup, one example agent (Planner), and one example tool (Filesystem). All other tools and agents are stubs only.

## Tasks

- [x] 1. Set up project structure and domain layer
  - [x] 1.1 Create Python package structure with all directories and `__init__.py` files
    - Create `autopilot/` root package with `__init__.py` and `__main__.py` entry point
    - Create sub-packages: `cli/`, `domain/entities/`, `domain/value_objects/`, `domain/interfaces/`, `application/orchestrator/`, `application/registries/`, `application/use_cases/`, `infrastructure/agents/`, `infrastructure/tools/`, `infrastructure/adapters/`
    - Add `__init__.py` to every package directory
    - Create `pyproject.toml` with dependencies: `langgraph`, `click`, `pyyaml`, `hypothesis` (dev)
    - _Requirements: 10.1_

  - [x] 1.2 Implement domain value objects (`error_record.py`, `log_entry.py`, `evidence.py`, `metrics.py`)
    - Implement `ErrorType` enum (RETRYABLE, NON_RETRYABLE) and `ErrorRecord` dataclass
    - Implement `StepStatus` enum (SUCCESS, FAILED, SKIPPED) and `LogEntry` dataclass
    - Implement `EvidenceItem` dataclass
    - Implement `Metrics` dataclass
    - All imports from standard library only
    - _Requirements: 5.1, 7.3, 10.2, 10.6_

  - [x] 1.3 Implement domain entities (`workflow_state.py`, `ticket.py`, `plan.py`, `config.py`)
    - Implement `WorkflowState` dataclass with all typed fields (ticket, context, modified_files, plan, logs, evidence, errors, metrics, metadata)
    - Implement `Ticket` dataclass
    - Implement `Plan` dataclass
    - Implement `Config` dataclass with validation constraints (MCPs ≤ 20, model ≤ 100 chars, provider ≤ 50 chars, timeout [1,600], max_retries [0,10])
    - All imports from standard library or domain package only
    - _Requirements: 5.1, 5.5, 6.2, 10.2, 10.6, 12.1_

  - [x] 1.4 Implement domain interfaces (`agent_interface.py`, `tool_interface.py`, `serializer.py`, `config_loader.py`)
    - Implement `AgentInterface` protocol with name, description, input_schema, output_schema properties and execute method with optional memory_context parameter
    - Implement `ToolInterface` protocol with name, input_schema, output_schema and execute method
    - Implement `ToolResult` dataclass (success, data, error)
    - Implement `SerializerInterface` protocol (serialize, deserialize)
    - Implement `ConfigLoaderInterface` protocol (load)
    - All imports from standard library or domain package only
    - _Requirements: 2.3, 4.1, 4.7, 10.2, 10.6, 12.2_

  - [x] 1.5 Write property tests for domain layer import constraint
    - **Property 19: Domain layer import constraint**
    - **Validates: Requirements 10.2, 10.6**

- [x] 2. Implement application-layer registries and retry policy
  - [x] 2.1 Implement `AgentRegistry` in `application/registries/agent_registry.py`
    - Register agents by unique name with error on duplicate
    - Retrieve agent by name with KeyError on missing
    - List all registered agent names
    - Import only from domain and standard library
    - _Requirements: 2.1, 2.5, 2.6, 10.3, 10.7_

  - [x] 2.2 Implement `ToolRegistry` in `application/registries/tool_registry.py`
    - Register tools by name
    - Retrieve tool by name with KeyError on missing (error message includes tool name)
    - Import only from domain and standard library
    - _Requirements: 4.5, 4.6, 10.3, 10.7_

  - [x] 2.3 Implement `RetryPolicy` in `application/orchestrator/retry_policy.py`
    - Define RETRYABLE_EXCEPTIONS and NON_RETRYABLE_EXCEPTIONS sets
    - Implement `classify(exception)` method returning ErrorType
    - Implement `get_delay(attempt)` for exponential backoff: `base_delay * backoff_multiplier^attempt`
    - Constructor accepts max_retries, base_delay, backoff_multiplier
    - _Requirements: 8.5, 8.6, 10.3, 10.7_

  - [x] 2.4 Write property tests for agent registry uniqueness
    - **Property 4: Agent registry uniqueness and non-interference**
    - **Validates: Requirements 2.5, 2.6**

  - [x] 2.5 Write property tests for tool registry lookup failure
    - **Property 5: Tool registry lookup failure**
    - **Validates: Requirements 4.6**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement infrastructure adapters (serializer, config loader, logger)
  - [x] 4.1 Implement `JSONSerializer` in `infrastructure/adapters/json_serializer.py`
    - Serialize WorkflowState to JSON (handle datetime, enums, dataclasses)
    - Deserialize JSON back to WorkflowState with type restoration
    - Report deserialization errors with failure type and field path/offset
    - Persist state to file, load state from file
    - _Requirements: 13.1, 13.2, 13.3, 13.5, 13.6_

  - [x] 4.2 Implement `YAMLConfigLoader` in `infrastructure/adapters/yaml_config_loader.py`
    - Load config from `config.yaml`
    - Validate all field constraints (MCPs ≤ 20, model ≤ 100 chars, provider ≤ 50 chars, timeout [1,600], max_retries [0,10])
    - Report missing required fields with field name in error message
    - Create default config file with inline comments if file does not exist
    - Support environment variable overrides with pattern `AUTOPILOT_<FIELD_NAME>`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 4.3 Implement `StructuredLogger` in `infrastructure/adapters/structured_logger.py`
    - Emit `[Agent_Name] <action>` on agent start
    - Emit agent name, elapsed_ms, and status on agent completion
    - Support verbosity levels: quiet, normal, verbose
    - Write execution log to JSON file on workflow completion
    - Handle filesystem write failure gracefully (continue terminal output, record error)
    - _Requirements: 7.1, 7.2, 7.4, 7.6, 7.7, 7.8_

  - [x] 4.4 Write property tests for WorkflowState serialization round-trip
    - **Property 1: WorkflowState serialization round-trip**
    - **Validates: Requirements 5.4, 12.6, 13.1, 13.2, 13.3**

  - [x] 4.5 Write property tests for config validation
    - **Property 2: Config validation accepts valid values and rejects invalid values**
    - **Validates: Requirements 6.2, 6.5**

  - [x] 4.6 Write property tests for environment variable override
    - **Property 3: Environment variable override**
    - **Validates: Requirements 6.6**

- [x] 5. Implement LangGraph orchestration engine and graph builder
  - [x] 5.1 Implement `GraphState` TypedDict with reducers in `application/orchestrator/engine.py`
    - Define LangGraph state schema with `Annotated` reducers: append for lists, overwrite for scalars
    - Implement `append_list` and `overwrite` reducer functions
    - _Requirements: 5.2, 3.1_

  - [x] 5.2 Implement `OrchestrationEngine` in `application/orchestrator/engine.py`
    - Constructor accepts agent_registry, serializer, logger, retry_policy, config
    - Implement agent node wrapper that extracts input_schema fields from state, calls agent.execute(), and returns output
    - Implement retry logic within node wrapper using RetryPolicy
    - Implement `execute(graph, state)` method to run compiled graph
    - Persist state after each node completes
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 2.2, 8.1, 8.2, 8.3, 8.4, 8.7, 13.6_

  - [x] 5.3 Implement `GraphBuilder` in `application/orchestrator/graph_builder.py`
    - Build work graph: Context_Builder → Planner → Code_Executor → Tester → Publisher → Documentation_Agent with conditional edges for retry
    - Build review graph (stub)
    - Build resume graph from a given node
    - Support conditional edges based on state values
    - _Requirements: 3.2, 3.4, 3.6, 3.7_

  - [x] 5.4 Write property tests for agent input extraction
    - **Property 6: Agent input extraction**
    - **Validates: Requirements 2.2**

  - [x] 5.5 Write property tests for state merge semantics
    - **Property 7: State merge semantics**
    - **Validates: Requirements 5.2**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement example agent (Planner) and tool stubs
  - [x] 7.1 Implement `PlannerAgent` in `infrastructure/agents/planner.py`
    - Implement AgentInterface protocol (name, description, input_schema, output_schema, execute)
    - Accept tool_registry via constructor injection
    - Execute method: receive ticket and context, produce a plan (placeholder logic for MVP)
    - Support optional memory_context parameter
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 4.2, 11.4, 12.2, 12.5_

  - [x] 7.2 Implement `FilesystemTool` in `infrastructure/tools/filesystem_tool.py`
    - Implement ToolInterface protocol (name, input_schema, output_schema, execute)
    - Execute method: basic file read/write/list operations
    - Return structured ToolResult (success/failure with data or error)
    - _Requirements: 4.1, 4.7_

  - [x] 7.3 Create stub agent implementations for remaining agents
    - Create stub `ContextBuilderAgent`, `CodeExecutorAgent`, `ReviewerAgent`, `TesterAgent`, `PublisherAgent`, `DocumentationAgent` in `infrastructure/agents/`
    - Each stub implements AgentInterface with appropriate name, description, schemas
    - Execute raises `NotImplementedError` with message indicating stub status
    - _Requirements: 2.1, 2.3_

  - [x] 7.4 Create stub tool implementations for remaining tools
    - Create stub `JiraTool`, `GitTool`, `GitHubTool`, `ObsidianTool`, `PlaywrightTool`, `OpenCodeTool` in `infrastructure/tools/`
    - Each stub implements ToolInterface with appropriate name, schemas
    - Execute raises `NotImplementedError` with message indicating stub status
    - _Requirements: 4.1, 4.4_

- [x] 8. Implement CLI and use cases
  - [x] 8.1 Implement CLI commands in `cli/commands.py`
    - Use Click to define CLI group with commands: `work`, `status`, `resume`, `config`, `review`
    - `work` command: validate ticket-id argument, initiate workflow, output execution ID
    - `status` command: display current workflow state (stub for MVP)
    - `resume` command: deserialize last state and resume workflow
    - `config` command: display current configuration in YAML format
    - `review` command: initiate review workflow (stub for MVP)
    - Handle missing arguments with error messages and non-zero exit codes
    - Unrecognized commands show help and exit with non-zero code
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 8.2 Implement `WorkCommand` use case in `application/use_cases/work_command.py`
    - Accept engine, config, serializer via constructor
    - Execute: create fresh WorkflowState, build work graph, run execution, return execution ID
    - _Requirements: 5.5, 5.6, 11.10_

  - [x] 8.3 Implement `ResumeCommand` use case in `application/use_cases/resume_command.py`
    - Load most recent persisted state
    - Identify resume point from execution logs
    - Build resume graph and execute
    - _Requirements: 1.3, 13.4_

  - [x] 8.4 Implement `ConfigCommand` use case in `application/use_cases/config_command.py`
    - Load and display current configuration in YAML format
    - _Requirements: 1.4_

  - [x] 8.5 Create stub use cases for `StatusCommand` and `ReviewCommand`
    - Implement with appropriate interfaces, raise `NotImplementedError` for body
    - _Requirements: 1.2, 1.5_

- [x] 9. Implement bootstrap and wiring
  - [x] 9.1 Implement `bootstrap.py` in `infrastructure/bootstrap.py`
    - Wire all dependencies: config loader → config → tools → tool_registry → agents → agent_registry → engine
    - Use constructor injection throughout
    - Return configured Application object ready for CLI consumption
    - _Requirements: 10.5, 4.5_

  - [x] 9.2 Implement `__main__.py` entry point
    - Import and invoke CLI, connecting bootstrap to command handlers
    - Handle top-level exceptions with appropriate exit codes
    - _Requirements: 1.7, 9.1_

  - [x] 9.3 Create default `config.yaml` template
    - Include all configuration fields with sensible defaults
    - Add inline YAML comments describing each field, constraints, and environment variable override pattern
    - _Requirements: 6.1, 6.4_

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Integration verification and application layer import constraint
  - [x] 11.1 Write property tests for application layer import constraint
    - **Property 20: Application layer import constraint**
    - **Validates: Requirements 10.3, 10.7**

  - [x] 11.2 Write integration tests for end-to-end CLI and workflow
    - Test `autopilot config` outputs YAML
    - Test `autopilot work` without ticket-id shows error and non-zero exit
    - Test work workflow with mocked agents produces correct state transitions
    - _Requirements: 1.1, 1.7, 1.8_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All tools beyond FilesystemTool are stubs — implement only the interface contract
- All agents beyond PlannerAgent are stubs — implement only the interface contract
- The MVP focuses on architectural correctness, not full workflow functionality
- Use Hypothesis for property-based testing with minimum 100 iterations per property

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4"] },
    { "id": 2, "tasks": ["1.5", "2.1", "2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5", "4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["4.4", "4.5", "4.6", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3"] },
    { "id": 6, "tasks": ["5.4", "5.5", "7.1", "7.2", "7.3", "7.4"] },
    { "id": 7, "tasks": ["8.1", "8.2", "8.3", "8.4", "8.5"] },
    { "id": 8, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 9, "tasks": ["11.1", "11.2"] }
  ]
}
```
