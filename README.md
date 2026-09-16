# Autopilot

Local workflow orchestration system for developers. Autopilot coordinates specialized agents and tools to automate the full development cycle — from fetching tickets to implementation, testing, documentation, and publishing.

Autopilot is **not** a code assistant. It is an orchestrator that coordinates existing tools (OpenCode, Jira, Git, etc.) through an agent-based architecture, running entirely on macOS with no cloud infrastructure dependencies.

## Why

**The problem.** Most of a developer's workflow around the code is repetitive and mechanical: fetch the ticket, gather context, plan, implement, test, commit with the right conventions, publish, document. None of it is hard — but it consumes attention, and skipped steps cause real friction (tickets left without transitions, inconsistent commit messages, runs without evidence).

**The idea.** Autopilot is an orchestrator, not an assistant. It doesn't try to be better at coding than the tools that already exist — instead it coordinates them: OpenCode implements, Jira tracks, git stores, Obsidian remembers. The value Autopilot adds is the plumbing: turning a ticket into a documented, tested, published run — and keeping an audit trail so you can always answer *what happened, when, and why*.

**Why this design.**

- **Agent per step** — each agent has one narrow responsibility, is testable in isolation, and can be swapped or extended without touching the others.
- **Graph orchestration** — workflows are explicit LangGraph state graphs: readable, resumable (state is persisted after every successful node), and easy to extend with new nodes.
- **Clean Architecture** — the domain has zero external dependencies; swapping Jira for another tracker, JSON persistence for SQLite, or OpenCode for another runner touches only the infrastructure layer.
- **Local-first** — everything runs on your machine: no cloud infrastructure, no data leaves your environment.

**Honest trade-offs.** The orchestrator is only as good as its agents: LLM calls dominate latency and results vary run to run. Some integrations are still stubs (git, github, playwright, Jira transitions) — the [Roadmap](#roadmap--whats-left-to-improve) reflects the gaps. The knowledge base starts as keyword-based JSON search — a deliberate first step before investing in a vector store.

## Table of Contents

- [Why](#why)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage — Command reference](#usage)
- [Agents](#agents)
- [Tools](#tools)
- [Persistence & Auditing](#persistence--auditing)
- [Error handling](#error-handling)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)
- [Project structure](#project-structure)
- [Roadmap](#roadmap--whats-left-to-improve)

## Quick Start

For someone who already has `opencode` installed and wants to run their first ticket:

```bash
# 1. Install autopilot (one time only)
cd or-dev-langchain-agent
pip3 install -e .

# 2. Create global config (one time only)
cp autopilot/.autopilot.yaml.template ~/.autopilot.yaml
# Edit ~/.autopilot.yaml: vault_location, llm_model, llm_provider

# 3. Export Jira credentials for the ticket's instance
#    (the ticket prefix defines the instance: PROJ-123 -> JIRA_PROJ_*)
export JIRA_PROJ_URL="https://your-domain.atlassian.net"
export JIRA_PROJ_EMAIL="you@email.com"
export JIRA_PROJ_TOKEN="your-api-token"

# 4. Move to the repo of the project you want to modify
cd /path/to/your/project

# 5. Run in dry-run first to validate the environment without touching anything
autopilot work PROJ-123 --dry-run

# 6. If everything looks good, run in real mode
autopilot work PROJ-123
```

If something fails in step 5/6, check [Troubleshooting](#troubleshooting) —
`autopilot work` validates the environment before starting and explains what's missing.

## Architecture

The project follows **Clean Architecture** principles with three well-defined layers:

```
autopilot/
├── domain/          # Entities, value objects and interfaces (no external dependencies)
├── application/     # Use cases, orchestrator and records
├── infrastructure/  # Concrete implementations: agents, tools, adapters, persistence
├── cli/             # Command line interface (Click)
└── .autopilot.yaml.template  # Configuration template
```

**Orchestration engine:** LangGraph StateGraph — models workflows as directed graphs where each node is a specialized agent.

**Injection pattern:** Constructor injection, wired in a centralized bootstrap module.

**Data flow:** A shared `WorkflowState` object flows through the graph, accumulating data as each agent contributes its output.

**Auditing:** Run Records + Ledger for full execution tracking with git persistence.

### Work graph

```
START → Context_Builder → Planner → Code_Executor → Tester → Publisher → Documentation_Agent → END
                                                        ↑                |
                                                        └── retry ───────┘ (if retryable error)
```

## Requirements

- Python 3.11+
- macOS (designed for local execution)
- [OpenCode](https://github.com/opencode-ai/opencode) installed and configured

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd or-dev-langchain-agent

# Install globally (recommended)
pip3 install -e .

# Or install in development mode
pip install -e ".[dev]"
```

After installing, the `autopilot` command will be available globally.

## Configuration

### Global config (one time only)

```bash
cp autopilot/.autopilot.yaml.template ~/.autopilot.yaml
```

Edit `~/.autopilot.yaml`:

```yaml
vault_location: "/Users/your-user/path/to/your/vault"
llm_model: "anthropic/claude-sonnet-4-20250514"
llm_provider: "anthropic"
```

**Note:** `workspace_location` is auto-detected from the directory where you run `autopilot`. There is no need to configure it. Each live ticket gets a deterministic Git worktree under `worktree_root` (or a sibling `.autopilot-worktrees` directory).

The loader looks for config in this order:
1. `.autopilot.yaml` in the current directory (per-project override)
2. `~/.autopilot.yaml` in your home (global config)

### Environment variables — Jira

```bash
# One instance per project/domain
export JIRA_PROJ_URL="https://your-domain.atlassian.net"
export JIRA_PROJ_EMAIL="you@email.com"
export JIRA_PROJ_TOKEN="your-api-token"

export JIRA_ACME_URL="https://another-domain.atlassian.net"
export JIRA_ACME_EMAIL="you@email.com"
export JIRA_ACME_TOKEN="another-token"
```

The instance is inferred automatically from the ticket prefix (PROJ-123 → JIRA_PROJ_*).

### Workflow rules (vault)

Create `.autopilot-rules.md` at the root of your Obsidian vault:

```markdown
# Workflow Rules

- branch_from: develop
- branch_pattern: feature/{ticket_id}
- commit_pattern: feat({ticket_id}): {description}
- jira_transition: In Progress -> Code Review
- push_remote: origin
```

If this file does not exist, default rules are used. It also looks for rules in loose notes as a fallback.

**Note:** `jira_transition` is read and reflected in the run metrics (`metrics.jira_update`),
but the Publisher **does not call the Jira API yet** to apply the transition or post
comments — `_update_jira` explicitly reports `{"skipped": true}`. Use
`autopilot ledger`/the run record to confirm the real state; do not assume the ticket
changed status just because you configured the rule.

### Environment variable override

All config fields support override:

```bash
export AUTOPILOT_TIMEOUT_SECONDS=120
export AUTOPILOT_MAX_RETRIES=5
export AUTOPILOT_VERBOSITY=verbose
```

## Usage

```bash
# From any project directory
cd /your/project

# Run the full workflow for a ticket
autopilot work PROJ-123

# Resume a ticket in its existing worktree
autopilot resume --ticket PROJ-123

# Run in dry-run mode (no real changes)
autopilot work PROJ-123 --dry-run

# View the loaded configuration
autopilot config

# Resume a paused or failed workflow
autopilot resume

# View the execution ledger
autopilot ledger

# View executions for a specific ticket
autopilot ledger --ticket PROJ-123

# View status (stub)
autopilot status

# Review workflow (stub)
autopilot review
```

### Command and flag reference

| Command | Flags | Description |
|---------|-------|-------------|
| `autopilot work TICKET_ID` | `--dry-run` · `--skip-validation` · `--config-path` | Runs the full workflow (Context_Builder → Planner → Code_Executor → Tester → Publisher → Documentation_Agent) for `TICKET_ID`. Validates config and environment before starting unless `--skip-validation` is passed. `--dry-run` does not make real commits/pushes. |
| `autopilot resume` | `--config-path` · `--ticket TICKET_ID` · `--answer "..."` | Resumes a paused or failed workflow from its existing ticket worktree; without `--ticket`, keeps the legacy current-workspace behavior. If the run is `BLOCKED` on a clarification question, `--answer` is required — it resumes the same node that asked, with the answer injected into context. |
| `autopilot config` | `--config-path` | Prints the effective configuration as YAML (after merging defaults + file + env vars). Useful for debugging which config is actually in use. |
| `autopilot ledger` | `--ticket TICKET_ID` · `--limit N` · `--config-path` | Shows the audit ledger summary. With `--ticket` filters by ticket; `--limit` caps how many entries are listed (total statistics always cover the full ledger). |
| `autopilot status` | — | Stub — not implemented yet. |
| `autopilot review` | — | Stub — not implemented yet. |

`--config-path` (default `auto`) accepts an explicit path to a `.autopilot.yaml`; if omitted, it is
auto-discovered following the order described in [Configuration](#configuration).

### Concurrent tickets

The Python application API can run independent tickets concurrently:

```python
app.run_many(["WPD-619", "WPD-620", "WPD-621"], approve=True)
```

Every ticket receives its own branch, filesystem path, Git index and OpenCode session. A dirty worktree is preserved during cleanup and is never removed implicitly.

Planner output also records approximate `expected_files`, `affected_modules` and `depends_on` values. Use `app.analyze_plans(...)` to decide whether tickets can run in parallel or need review/sequencing; overlap detection is advisory and does not block execution automatically.

## Agents

| Agent | What it does |
|--------|----------|
| **Context_Builder** | Fetches the Jira ticket + searches for relevant notes in the Obsidian vault |
| **Planner** | Sends context to OpenCode and generates a structured implementation plan |
| **Code_Executor** | Executes each plan step via `opencode run` |
| **Tester** | Detects the project type (Node/Python) and runs tests automatically |
| **Publisher** | Validates the ticket worktree, then commits and pushes its branch according to project conventions |
| **Documentation_Agent** | Generates a markdown summary of the work done |
| **Reviewer** | Code review workflow (pending) |

## Tools

| Tool | Description |
|-------------|-------------|
| **opencode** | Runs prompts via `opencode run` (batch mode) |
| **jira** | Atlassian REST API v2/v3 — fetch, transitions, comments, subtasks, JQL search |
| **obsidian** | Keyword search in local vault (relevance scoring) |
| **filesystem** | File read/write/list operations |
| git | Git operations via subprocess (stub — Publisher does it directly) |
| github | GitHub API interaction (pending) |
| playwright | Browser automation (pending) |

### Jira Tool — Available actions

| Action | Description |
|--------|-------------|
| `get_ticket` | Get ticket details (summary, description, status, labels, comments) |
| `get_transitions` | List available transitions for the ticket |
| `apply_transition` | Apply a transition by name (case-insensitive) |
| `comment` | Post a comment (auto-converts Markdown to wiki markup) |
| `create_subtask` | Create a sub-task under a parent ticket |
| `search_jql` | Search issues using JQL |
| `status_entered_at` | Get the timestamp of the last entry to a status (for idempotency) |

## Persistence & Auditing

### Run Records

Each execution produces a **RunRecord** that captures the full cycle:

- **Identity:** run_id, ticket_id, ticket_title
- **Time:** started_at, finished_at, duration_seconds
- **Result:** status (running/completed/failed/cancelled), verdict (PASS/FAIL/BLOCKED)
- **Content:** executed plan, modified files, tests (executed/passed/failed)
- **Audit:** logs, errors, evidence, tokens_used, cost_usd

**Note:** `tokens_used`/`cost_usd` are in the schema for a future integration,
but no current agent/tool reports token usage or cost back to the engine —
in practice they always remain `null`. Do not use them as a real cost source yet.

Location: `{workspace}/runs/{run_id}/run-record.json` for the repository-level run record; the resumable `.autopilot_state.json` lives inside the ticket's worktree.

### Ledger

The **Ledger** is the central audit record. Each execution adds an entry:

- Idempotent by run_id (re-running replaces the entry)
- Offline Markdown summary without needing Jira
- History by ticket

Location: `{workspace}/ledger.json`

### Git Persistence

The ledger is committed to a dedicated `autopilot-results` branch for:

- Version history of all executions
- Diff between runs
- Offline access to historical data
- Single-writer pattern for concurrency

Concurrency is also enforced at the process level: a per-workspace **run lock**
prevents two workflows from running at once in the same workspace, and ledger/run
record writes are **atomic** (`infrastructure/persistence/file_lock.py`, `atomic_write.py`).

### Automatic test detection

The Tester detects the framework based on the project files:

| File found | Framework | Command |
|---|---|---|
| `package.json` with jest | Jest | `npm test` |
| `package.json` with mocha | Mocha | `npm test` |
| `package.json` with vitest | Vitest | `npx vitest run` |
| `pyproject.toml` | Pytest | `python3 -m pytest --tb=short` |
| `Makefile` with test target | Make | `make test` |

## Error handling

- **Retryable errors** (timeout, network, failed tests): automatic retries with exponential backoff
- **Non-retryable errors** (authentication, configuration, schema): immediate workflow pause
- **Clarification needed**: when Planner determines a ticket is genuinely ambiguous (it would let OpenCode produce two materially different, equally "valid" implementations), it stops and asks a specific question instead of guessing. The run pauses with status `blocked` and verdict `BLOCKED` — no retry, since the question won't answer itself — and the question is shown in the workflow report. Answer it with `autopilot resume --ticket TICKET_ID --answer "..."`, which resumes Planner itself (not the next node) with the answer folded into its prompt.
- State is persisted after each successful node to allow resuming with `autopilot resume`

## Troubleshooting

Common messages when running `autopilot work`/`resume`/`config`/`ledger` and how to resolve them:

| Message / symptom | Cause | Solution |
|---|---|---|
| `workspace_location must not be empty` / `vault_location must not be empty` | The config does not have those fields filled in (`config_sanity_validator`, runs before anything else) | Fill in `vault_location` in `~/.autopilot.yaml`. `workspace_location` is auto-detected from the CWD; do not leave it empty manually if you overrode it. |
| `workspace_location is not creatable: ...` | The configured path does not exist and no ancestor folder is writable | Use a path under a directory with write permissions, or create the directory manually. |
| `opencode not found in PATH` | The `opencode` binary is not installed or not in the `PATH` | Install [OpenCode](https://github.com/opencode-ai/opencode) and verify with `which opencode`. |
| `Vault directory not found: ...` | `vault_location` points to a folder that does not exist | Fix the path in `~/.autopilot.yaml` (it must be the root of your Obsidian vault). |
| `Jira credentials incomplete for instance 'X'` (warning) | `JIRA_X_URL` / `JIRA_X_EMAIL` / `JIRA_X_TOKEN` are missing for the ticket prefix (e.g. `PROJ-123` → instance `PROJ`) | Export the three environment variables for that instance. Without them, Context_Builder simply skips the Jira fetch (it does not block the run). |
| The command runs but never creates/pushes a branch | You are running `--dry-run`, or `.autopilot-rules.md` does not define valid rules | Remove `--dry-run` for a real run; check that `.autopilot-rules.md` exists at the vault root with the expected format (see [Workflow rules](#workflow-rules-vault)). |
| The ticket status does not change in Jira even though I configured `jira_transition` | Publisher does not implement the real Jira API call for transitions yet | Expected behavior for now — see the note in [Workflow rules](#workflow-rules-vault) and the roadmap. Apply the transition manually in Jira. |
| `Not a git repository, skipping ledger commit` (log) | The `workspace_location` is not a git repo | Not a blocking error: the ledger is still saved in `ledger.json`, only the commit to `autopilot-results` is skipped. Initialize a git repo there if you want that versioned history. |
| `autopilot resume` fails with `State file not found: ...` | There is no `.autopilot_state.json` in the workspace (no previous run persisted state) | Run `autopilot work TICKET_ID` first; `resume` only applies to workflows that failed or paused midway. |
| I changed `~/.autopilot.yaml` but I don't see the effect | There is a `.autopilot.yaml` in the project directory (local override) that takes priority | Check `autopilot config` to see which file was actually loaded, or delete/adjust the local override. |

If the message is not in this table, run with an explicit `--config-path` and without `--skip-validation`
to get the most detailed diagnosis possible before reporting it.

## Tests

```bash
# Run the whole suite
python3 -m pytest

# With verbose output
python3 -m pytest -v

# Only one component's tests
python3 -m pytest tests/test_jira_markdown.py -v
python3 -m pytest tests/test_run_record.py -v
python3 -m pytest tests/test_ledger.py -v
```

The suite includes property, unit, and integration tests.

## Project structure

```
autopilot/
├── __init__.py
├── __main__.py                    # Entry point: python -m autopilot
├── .autopilot.yaml.template       # Configuration template
├── cli/
│   └── commands.py                # CLI commands (Click)
├── domain/
│   ├── entities/                  # WorkflowState, Ticket, Plan, Config, RunRecord, LedgerEntry
│   ├── value_objects/             # ErrorRecord, LogEntry, EvidenceItem, Metrics, Exceptions
│   └── interfaces/                # AgentInterface, ToolInterface, SerializerInterface
├── application/
│   ├── orchestrator/              # OrchestrationEngine, GraphBuilder, RetryPolicy
│   ├── registries/                # AgentRegistry, ToolRegistry
│   ├── use_cases/                 # WorkCommand, ResumeCommand, ConfigCommand
│   └── knowledge/                 # ExperienceBuilder
└── infrastructure/
    ├── agents/                    # ContextBuilder, Planner, CodeExecutor, Tester, Publisher, Documentation
    ├── tools/                     # OpenCode, Jira, Obsidian, Filesystem + stubs
    ├── adapters/                  # JSONSerializer, YAMLConfigLoader, StructuredLogger
    ├── knowledge/                 # JsonKnowledgeEngine
    ├── persistence/               # RunRecordStore, Ledger, LedgerCommitter
    └── bootstrap.py               # Dependency wiring (DI)
```

## Roadmap — What's left to improve

### Already implemented (verified in code, not in the original roadmap)

- [x] **OpenCode sessions**: `OpenCodeTool` uses `--continue` to keep context between steps (`opencode_tool.py`)
- [x] **Real terminal logging**: `StructuredLogger` is connected to `OrchestrationEngine` (`log_agent_start`/`log_agent_completion`/`log_retry`)
- [x] **More detailed workflow output**: `autopilot work` prints a report with modified files, tests, errors and evidence (`cli/commands.py`)
- [x] **Workspace detection**: `workspace_location` is auto-detected from the CWD in `yaml_config_loader.py` (override via `AUTOPILOT_WORKSPACE_LOCATION`)
- [x] **Pre-execution validation**: `validate_environment` checks opencode/git availability, vault and workspace paths, and Jira credentials; `config_sanity_validator` runs first in every command (`infrastructure/validators.py`)
- [x] **Knowledge base (Memory/RAG MVP)**: each run is stored as an `Experience` via `ExperienceBuilder` + `JsonKnowledgeEngine`; the Planner queries similar past experiences and includes them in its planning prompt (`application/knowledge/`, `infrastructure/knowledge/`)

### High priority

- [ ] **Real Jira transition**: Publisher reads `jira_transition` but does not call the Jira API yet (`_update_jira` always reports `skipped`) — see the note in "Workflow rules"

### Medium priority

- [ ] **Automatic PR**: Publisher creates a PR in GitHub/GitLab after the push
- [ ] **Reviewer agent**: Pre-merge code analysis via OpenCode (agent and `review` command are connected stubs but not implemented; see `ReviewCommand`/`build_review_graph`)
- [ ] **Playwright tests**: Integrate E2E tests for projects with frontend
- [ ] **Multiple config merge**: Global config + per-project config (specific override)
- [ ] **Failure diagnostics**: Use an LLM to generate failure diagnostics for operators

### Low priority

- [x] **Ticket isolation**: Run multiple tickets concurrently in independent Git worktrees
- [ ] **Parallel execution**: Run independent plan steps in parallel
- [ ] **Web UI**: Dashboard to view the status of active workflows
- [ ] **Plugin system**: Allow adding custom agents and tools without modifying the core
- [ ] **Metrics and analytics**: Time per agent, success rate, tokens consumed

## License

Private project. See [LICENSE](LICENSE).
