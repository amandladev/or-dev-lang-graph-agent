# AGENTS.md — Autopilot Project Context

> Essential project context for AI agents working in this repository.

## What Autopilot Is

Autopilot is a **local workflow orchestration system** for developers. It coordinates
specialized agents to automate the development lifecycle:
ticket → implementation → tests → commit → documentation.

It is an orchestrator for existing tools, not a coding assistant.

## Technology Stack

- **Language:** Python 3.11+
- **Orchestration:** LangGraph StateGraph
- **CLI:** Click
- **Configuration:** YAML with environment variable overrides
- **Testing:** pytest + Hypothesis (property-based)
- **Persistence:** JSON files + `autopilot-results` Git branch

## Architecture

```
autopilot/
├── domain/          # Entities, value objects, interfaces (no external dependencies)
├── application/     # Use cases, orchestration, registries
├── infrastructure/  # Agents, tools, adapters, persistence implementations
└── cli/             # Click CLI
```

**Dependency rule:** Infrastructure → Application → Domain (inward only).

## Main Workflow

```
autopilot work TICKET-ID
    ↓
WorkCommand.execute()
    ↓
OrchestrationEngine.execute(graph, state, run_record)
    ↓
Graph: Context_Builder → Planner → Code_Executor → Tester → Publisher → Documentation
    ↓
RunRecord saved → Ledger entry → Git commit to autopilot-results
    ↓
Experience stored → Knowledge Engine (queried by Planner in future runs)
```

## Key Files

| File | Purpose |
|---------|-----------|
| `infrastructure/bootstrap.py` | Dependency injection wiring |
| `application/orchestrator/engine.py` | Execution engine with retries and RunRecord tracking |
| `application/orchestrator/graph_builder.py` | LangGraph graph construction |
| `application/use_cases/work_command.py` | Main use case |
| `domain/entities/workflow_state.py` | Shared graph state |
| `domain/entities/run_record.py` | Complete execution record schema |
| `domain/entities/ledger_entry.py` | Audit ledger entry |
| `infrastructure/persistence/run_record_store.py` | Run record persistence |
| `infrastructure/persistence/ledger.py` | Central audit ledger |
| `infrastructure/persistence/ledger_committer.py` | Ledger Git commits |
| `infrastructure/persistence/file_lock.py` | Workspace and ledger locks |
| `infrastructure/persistence/atomic_write.py` | Atomic ledger and run record writes |
| `infrastructure/validators.py` | Pre-execution environment and configuration validation |
| `application/knowledge/experience_builder.py` | Builds Experience entities from final run state |
| `infrastructure/knowledge/json_knowledge_engine.py` | JSON experience storage and search |
| `infrastructure/tools/jira_tool.py` | Extended Jira client |
| `cli/commands.py` | CLI commands |

## Agents

| Agente | Input | Output |
|--------|-------|--------|
| Context_Builder | ticket_id | context (ticket data + vault notes) |
| Planner | ticket, context, metadata | plan (structured steps informed by similar experiences) |
| Code_Executor | plan, context | modified_files, evidence |
| Tester | modified_files, context | evidence (test results) |
| Publisher | modified_files, context | — |
| Documentation_Agent | all state | — |

## Tools

| Tool | Actions |
|------|----------|
| JiraTool | get_ticket, get_transitions, apply_transition, comment, create_subtask, search_jql, status_entered_at |
| OpenCodeTool | execute (opencode run) |
| ObsidianTool | search |
| FilesystemTool | read, write, list |

## Configuration

```yaml
# ~/.autopilot.yaml
vault_location: "/path/to/obsidian/vault"
# workspace_location is auto-detected from the CWD
llm_model: "anthropic/claude-sonnet-4-20250514"
llm_provider: "anthropic"
timeout_seconds: 300
max_retries: 3
verbosity: normal  # quiet | normal | verbose
```

Env vars: `JIRA_<INSTANCE>_URL`, `JIRA_<INSTANCE>_EMAIL`, `JIRA_<INSTANCE>_TOKEN`
Override: `AUTOPILOT_WORKSPACE_LOCATION` (force a specific workspace)

## Persistence

### Run Records
- Location: `{workspace}/runs/{run_id}/run-record.json`
- One record per execution
- Contains status, verdict, tests, logs, errors, evidence, and metrics

### Ledger
- Location: `{workspace}/ledger.json`
- Central and idempotent by run ID
- Committed to the `autopilot-results` branch

### Concurrency
- A per-workspace run lock prevents concurrent runs
- Ledger and run records use atomic writes

### Knowledge base (Memory/RAG MVP)
- Each completed run produces an `Experience` stored in `{workspace}/knowledge/experiences/{id}.json`
- Planner queries similar experiences using keyword scoring and includes them in its prompt

## CLI Commands

```bash
autopilot work TICKET-ID            # Run a workflow
autopilot work TICKET-ID --dry-run  # Run without applying changes
autopilot resume                    # Resume a paused workflow
autopilot config                    # Display configuration
autopilot ledger                    # Display the run summary
autopilot ledger --ticket TICKET    # Display runs for one ticket
autopilot status                   # Stub
autopilot review                   # Stub
```

## Testing

```bash
python3 -m pytest                  # Full test suite
python3 -m pytest -v               # Verbose
python3 -m pytest tests/test_run_record.py  # Specific test module
```

## Conventions

1. Avoid code comments unless they explain non-obvious behavior
2. Domain must not import from infrastructure
3. Add type hints to all public functions
4. Use dataclasses for entities and value objects
5. Return `ToolResult` from tools (`success`, `data`, `error`)
6. Create `RunRecord` at startup and update it throughout execution

## Known Limitations

- `git_tool.py`, `github_tool.py`, and `playwright_tool.py` are stubs
- `ReviewerAgent`, `status`, and `review` are stubs
- Publisher reads `jira_transition` but does not call the Jira API
- LedgerCommitter silently skips commits when the workspace is not a Git repository
