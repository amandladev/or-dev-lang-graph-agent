# Requirements Document

## Introduction

Autopilot is a local personal operating system for developer workflows. It coordinates specialized agents and tools to fully automate daily development tasks — from ticket intake through implementation, testing, and documentation. Autopilot is NOT a code assistant; it orchestrates existing specialized tools (OpenCode, Playwright, Jira, etc.) through an agent-based architecture running entirely on macOS without cloud infrastructure dependencies.

The system follows Clean Architecture principles with SOLID design, dependency injection, and clear separation between domain, application, and infrastructure layers. Agents coordinate work but contain no business logic. Tools are replaceable abstractions accessed only through defined interfaces.

## Glossary

- **Orchestrator**: The LangGraph-based engine that coordinates agent execution as a directed graph
- **Agent**: A specialized node in the orchestration graph with a single responsibility (e.g., Planner, Context_Builder, Code_Executor, Reviewer, Tester, Publisher, Documentation_Agent)
- **Tool**: An independent infrastructure adapter that provides access to external systems (e.g., Jira_Tool, Git_Tool, GitHub_Tool, Obsidian_Tool, Playwright_Tool, OpenCode_Tool, Filesystem_Tool)
- **Workflow_State**: A shared, structured object containing all data for a workflow execution (ticket, context, modified files, plan, logs, evidence, errors, metrics)
- **CLI**: The command-line interface serving as the primary user interaction point
- **Config**: A YAML-based configuration file defining vault location, workspace location, available MCPs, LLM model, provider, timeouts, and max retries
- **MCP**: Model Context Protocol — a protocol for connecting to external tool servers
- **Execution_Log**: A structured record of each step's inputs, outputs, timing, and status during a workflow run
- **Retryable_Error**: An error classified as transient and recoverable through re-execution (test failure, transient network issue, or tool timeout)
- **Non_Retryable_Error**: An error classified as permanent and requiring human intervention (authentication failure, missing configuration, or schema violation)

## Requirements

### Requirement 1: CLI Interface

**User Story:** As a developer, I want a CLI interface to invoke autopilot commands, so that I can trigger and monitor automated workflows from my terminal.

#### Acceptance Criteria

1. WHEN the user executes `autopilot work <ticket-id>`, THE CLI SHALL validate the ticket-id format and initiate a full workflow execution for the specified ticket, outputting the workflow execution ID to stdout
2. WHEN the user executes `autopilot status`, THE CLI SHALL display the current state of the active workflow execution including the current agent node, elapsed time, and step count
3. WHEN the user executes `autopilot resume`, THE CLI SHALL resume a previously paused or failed workflow from its last successful step by deserializing the persisted Workflow_State
4. WHEN the user executes `autopilot config`, THE CLI SHALL display the current configuration values in YAML format to stdout
5. WHEN the user executes `autopilot review`, THE CLI SHALL initiate a review workflow for the current working context
6. IF an unrecognized command is provided, THEN THE CLI SHALL display available commands with usage descriptions and exit with a non-zero exit code
7. WHEN any command is executed, THE CLI SHALL exit with code 0 on success and a non-zero exit code on failure
8. IF the `autopilot work` command is invoked without a ticket-id argument, THEN THE CLI SHALL output an error message indicating the required argument and exit with a non-zero exit code

### Requirement 2: Agent Architecture

**User Story:** As a developer, I want specialized agents with single responsibilities, so that each agent can be developed, tested, and replaced independently.

#### Acceptance Criteria

1. THE Agent_Registry SHALL register each agent with a name (unique string identifier), description (human-readable text), input schema (typed dictionary specification), and output schema (typed dictionary specification)
2. WHEN an agent is invoked, THE Orchestrator SHALL provide only the fields declared in the agent's input schema extracted from the Workflow_State
3. THE Agent SHALL expose only its name, description, input schema, and output schema to the Orchestrator through a standard metadata interface
4. THE Agent SHALL contain no business logic beyond coordination of its assigned tools; all domain logic SHALL reside in the tools or the domain layer
5. WHEN a new agent is added to the system, THE Agent_Registry SHALL make the agent available by registration without modifications to existing agents or the Orchestrator
6. IF an agent with a duplicate name is registered, THEN THE Agent_Registry SHALL raise an error indicating the conflicting name
7. WHEN an agent is invoked and its execution raises an exception, THE Agent SHALL propagate the exception to the Orchestrator with the original error type preserved

### Requirement 3: Orchestration Engine

**User Story:** As a developer, I want a graph-based orchestration engine, so that workflow execution is predictable, extensible, and decoupled from agent internals.

#### Acceptance Criteria

1. THE Orchestrator SHALL execute agents as nodes in a LangGraph directed graph
2. WHEN a workflow is initiated, THE Orchestrator SHALL traverse the graph from the start node to the end node, invoking each agent in the order defined by the graph edges
3. THE Orchestrator SHALL pass the Workflow_State to each agent node and receive the updated Workflow_State as output
4. WHEN a new agent node is added to the graph definition, THE Orchestrator SHALL incorporate the node without changes to existing node implementations
5. THE Orchestrator SHALL not access internal implementation details of any agent; it SHALL interact only through the agent's declared interface
6. THE Orchestrator SHALL support conditional edges that route to different nodes based on Workflow_State values (e.g., retry on error, skip steps based on status)
7. THE Orchestrator SHALL support multiple workflow types (work, review, resume) as distinct graph definitions
8. WHEN an agent node raises an exception, THE Orchestrator SHALL evaluate the error type against the retry policy before propagating or retrying

### Requirement 4: Tools Layer

**User Story:** As a developer, I want an independent tools layer with replaceable implementations, so that I can swap tool backends without affecting agents.

#### Acceptance Criteria

1. THE Tool SHALL implement a defined interface specifying its name, input schema, output schema, and execute method
2. WHEN an agent requires access to an external system, THE Agent SHALL invoke the corresponding Tool through its interface using the tool's registered name as the lookup key
3. THE Agent SHALL not access external systems (Jira, Git, GitHub, Obsidian, Playwright, OpenCode, filesystem) directly
4. WHEN a Tool implementation is replaced, THE replacement SHALL conform to the same interface such that zero code changes are required in any agent that uses it
5. THE Tool_Registry SHALL provide tool instances to agents through dependency injection based on tool name
6. IF an agent requests a tool name that is not registered in the Tool_Registry, THEN THE Tool_Registry SHALL raise an error indicating the unregistered tool name
7. WHEN a Tool's execute method completes, THE Tool SHALL return a structured result containing a success or failure status and either the output data on success or an error description on failure

### Requirement 5: Workflow State Management

**User Story:** As a developer, I want a shared structured state for each workflow execution, so that all agents can read and contribute data without global variables.

#### Acceptance Criteria

1. THE Workflow_State SHALL contain typed fields for: ticket (object), context (object), modified_files (list of strings), plan (object), logs (list of log entries), evidence (list of evidence items), errors (list of error records), metrics (object), and metadata (dictionary with string keys and JSON-serializable values)
2. WHEN an agent completes execution, THE Orchestrator SHALL merge the agent's output into the Workflow_State using an append strategy for list fields and an overwrite strategy for scalar and object fields
3. THE Workflow_State SHALL be the sole mechanism for data sharing between agents; no agent SHALL access another agent's output except through the Workflow_State
4. THE Workflow_State SHALL guarantee that for any valid instance, serializing to JSON and deserializing produces an object with field-by-field equality to the original (round-trip property)
5. THE Workflow_State SHALL not use global variables or module-level mutable state; each workflow execution SHALL create a new Workflow_State instance
6. WHEN a workflow is initiated, THE Orchestrator SHALL create a Workflow_State instance with all fields initialized to their empty or default values before invoking the first agent node

### Requirement 6: Configuration System

**User Story:** As a developer, I want all settings in a YAML configuration file, so that I can customize autopilot behavior without code changes.

#### Acceptance Criteria

1. THE Config_Loader SHALL read configuration from a `config.yaml` file located in the project root directory at startup
2. THE Config SHALL support fields for: vault location (filesystem path), workspace location (filesystem path), available MCPs (list, maximum 20 entries), LLM model (string, maximum 100 characters), LLM provider (string, maximum 50 characters), timeouts in seconds (integer, range 1 to 600), and max retries (integer, range 0 to 10)
3. WHEN a required configuration field is missing, THE Config_Loader SHALL output an error message to stderr indicating the missing field name and exit with a non-zero exit code
4. WHEN the configuration file does not exist, THE Config_Loader SHALL create a default configuration file with inline YAML comments describing each field and then exit with a non-zero exit code indicating the user must review the configuration before proceeding
5. IF a configuration value fails type or constraint validation, THEN THE Config_Loader SHALL output an error message to stderr indicating the field name, the provided value, and the expected constraint, and exit with a non-zero exit code
6. WHEN an environment variable matching the pattern `AUTOPILOT_<FIELD_NAME>` is set, THE Config_Loader SHALL use the environment variable value in place of the corresponding YAML field value

### Requirement 7: Observability and Logging

**User Story:** As a developer, I want structured step-by-step logging with agent-prefixed output, so that I can monitor and debug workflow execution in real time.

#### Acceptance Criteria

1. WHEN an agent begins execution, THE Logger SHALL emit a log entry to the terminal with the format `[Agent_Name] <action description>` where Agent_Name matches the registered agent name
2. WHEN an agent completes execution, THE Logger SHALL emit a log entry including the agent name, elapsed time in milliseconds, and a status value of "success", "failed", or "skipped"
3. THE Execution_Log SHALL record for each step: agent name, start timestamp, end timestamp, elapsed time in milliseconds, input data, output data, and status value
4. WHEN a workflow completes, THE Logger SHALL produce a final summary including total duration in milliseconds, number of steps executed, number of steps with status "failed", and number of steps with status "skipped"
5. THE Execution_Log SHALL be queryable after workflow completion by agent name, by status value, and by step execution order
6. THE Logger SHALL support verbosity levels of "quiet", "normal", and "verbose" where "quiet" emits only errors and the final summary, "normal" emits agent start and completion entries, and "verbose" additionally emits input and output data for each step
7. THE Logger SHALL write real-time output to the terminal and THE Execution_Log SHALL persist the complete execution history to the local filesystem as a structured JSON file
8. IF the Logger fails to write to the filesystem, THEN THE Logger SHALL continue emitting output to the terminal and record the write failure in the Workflow_State errors field

### Requirement 8: Error Handling and Retry

**User Story:** As a developer, I want automatic retry on simple errors with configurable limits, so that transient failures do not require manual intervention.

#### Acceptance Criteria

1. WHEN an agent execution fails with a retryable error (test failure, transient network issue, or tool timeout), THE Orchestrator SHALL retry the agent up to the configured max retries value (between 1 and 10, inclusive)
2. WHEN the maximum retry count is reached, THE Orchestrator SHALL pause the workflow, record the error type, error description, agent name, and attempt count in the Workflow_State errors field, and persist the Workflow_State for later resumption
3. IF a non-retryable error occurs (authentication failure, missing configuration, or schema violation), THEN THE Orchestrator SHALL immediately pause the workflow, record the error type, error description, and agent name in the Workflow_State errors field, and persist the Workflow_State for later resumption
4. WHEN retrying an agent, THE Orchestrator SHALL log each retry attempt with the attempt number, maximum attempt limit, agent name, and error description
5. THE Config SHALL define the maximum number of retries (default: 3) and the base delay between retry attempts (default: 2 seconds), supporting a configurable backoff multiplier (default: 2) applied to the base delay on each successive attempt
6. WHEN an agent execution fails, THE Orchestrator SHALL classify the error as retryable or non-retryable based on the Python exception type before deciding the retry or pause action
7. WHEN a workflow is paused due to error, THE Orchestrator SHALL discard the failed agent's partial output and preserve the Workflow_State as it existed after the last successfully completed agent

### Requirement 9: Local Execution Constraint

**User Story:** As a developer, I want the system to run entirely on macOS without cloud infrastructure, so that I maintain full control and privacy over my workflow data.

#### Acceptance Criteria

1. THE System SHALL execute all orchestration, agent coordination, state management, and logging operations on the local macOS machine without requiring cloud services for these functions
2. THE System SHALL not require Docker or container runtimes for execution
3. THE System SHALL not require Kubernetes or container orchestration platforms
4. THE System SHALL store all state, configuration, execution logs, and persisted Workflow_State on the local filesystem
5. WHEN external APIs are invoked (e.g., Jira, GitHub, LLM providers), THE Tool SHALL connect directly from the local machine without proxy infrastructure
6. THE System SHALL permit outbound API calls to external services (Jira, GitHub, LLM providers) as configured in config.yaml; these calls SHALL NOT constitute a cloud infrastructure dependency

### Requirement 10: Clean Architecture

**User Story:** As a developer, I want the codebase to follow Clean Architecture with separated layers, so that the system remains maintainable and testable as it grows.

#### Acceptance Criteria

1. THE System SHALL organize code into three distinct Python packages: a domain package, an application package, and an infrastructure package
2. THE domain package SHALL contain entity definitions, value objects, and interface contracts, and SHALL NOT contain import statements referencing the application package or the infrastructure package
3. THE application package SHALL contain use cases and orchestration logic, and SHALL NOT contain import statements referencing the infrastructure package
4. THE infrastructure package SHALL contain concrete implementations of tools, adapters, and external integrations, and SHALL import from the domain package for interface contracts
5. THE System SHALL use constructor injection to provide infrastructure implementations to application layer components at runtime
6. WHEN a Python module is added to the domain package, THE module SHALL import only from the Python standard library or from other modules within the domain package
7. WHEN a Python module is added to the application package, THE module SHALL import only from the Python standard library, the domain package, or other modules within the application package

### Requirement 11: Full Workflow Execution

**User Story:** As a developer, I want to execute `autopilot work <ticket-id>` and have the system complete the full development cycle automatically, so that I only need to supervise.

#### Acceptance Criteria

1. WHEN `autopilot work <ticket-id>` is executed, THE System SHALL fetch the ticket details from Jira via the Jira_Tool and store the result in the Workflow_State ticket field
2. IF the Jira_Tool fails to fetch the ticket (network error, authentication failure, or ticket not found), THEN THE System SHALL record the error in the Workflow_State and pause the workflow before proceeding to context building
3. WHEN ticket details are available, THE Context_Builder SHALL search related documentation and Obsidian notes to build a unified context and store it in the Workflow_State context field
4. WHEN context is assembled, THE Planner SHALL create an implementation plan and store it in the Workflow_State plan field
5. WHEN the plan is ready, THE Code_Executor SHALL invoke the code agent (OpenCode) to implement the plan
6. WHEN implementation is complete, THE Tester SHALL run tests and Playwright checks and store results in the Workflow_State evidence field
7. IF tests fail with a retryable error as classified by the retry policy, THEN THE Orchestrator SHALL retry the Code_Executor with the error context appended to the Workflow_State
8. WHEN tests pass, THE Publisher SHALL generate evidence (test results, Playwright screenshots, execution logs) and update the Jira ticket status
9. WHEN publishing is complete, THE Documentation_Agent SHALL generate a final summary and store proposed Obsidian documentation in the Workflow_State for user review
10. THE Orchestrator SHALL track step completion order in the Workflow_State, ensuring each step executes only after its predecessor completes successfully

### Requirement 12: Memory Architecture Preparation

**User Story:** As a developer, I want the architecture to accommodate future memory capabilities, so that memory can be added without restructuring the system.

#### Acceptance Criteria

1. THE Workflow_State SHALL include a metadata field typed as a dictionary with string keys and JSON-serializable values, reserved for future memory-related data
2. THE Agent interface SHALL support an optional memory context parameter in its input schema, typed as an optional dictionary with string keys and JSON-serializable values, defaulting to None when not provided
3. THE System SHALL not implement memory retrieval or storage in the MVP
4. WHEN a memory-capable agent is registered, THE Agent_Registry SHALL register it using the same registration mechanism (name, description, input schema, output schema) as non-memory agents without modifications to the Orchestrator
5. WHEN the memory context parameter is None, THE Agent SHALL execute its workflow identically to an agent without memory support
6. THE Workflow_State metadata field SHALL be included in serialization and deserialization, preserving all stored key-value pairs across round-trips

### Requirement 13: Workflow State Serialization

**User Story:** As a developer, I want workflow state to be serializable, so that workflows can be paused, resumed, and inspected.

#### Acceptance Criteria

1. THE Serializer SHALL convert Workflow_State objects into JSON format, handling all Workflow_State fields including nested objects (ticket, context, modified files, plan, logs, evidence, errors, metrics, and metadata)
2. THE Deserializer SHALL reconstruct Workflow_State objects from JSON format, restoring all fields to their original types and values
3. THE System SHALL guarantee that for any valid Workflow_State object, serializing and then deserializing produces an object with field-by-field equality to the original (round-trip property)
4. WHEN the `autopilot resume` command is executed, THE System SHALL deserialize the most recent persisted state file and resume execution from the first agent node after the last node recorded with a success status in the Execution_Log
5. IF a serialized state file contains invalid JSON or does not conform to the Workflow_State schema, THEN THE Deserializer SHALL return an error indicating the failure type (parse error or schema violation) and the field path or character offset where validation failed
6. WHEN the Orchestrator completes an agent node execution, THE System SHALL serialize and persist the current Workflow_State to the configured storage location before proceeding to the next node
