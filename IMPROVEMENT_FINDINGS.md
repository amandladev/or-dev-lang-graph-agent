# Autopilot — Improvement Findings

Generated from a codebase analysis on 2026-07-14. These are concrete, evidence-based
issues found across the orchestration engine, agents, and persistence layer.

## Security

1. **Shell injection in Publisher git commands** (`autopilot/infrastructure/agents/publisher.py`)
   `_git_cmd` runs `subprocess.run(cmd, shell=True, ...)` where `cmd` embeds `commit_msg`
   and `branch_name`, both built from untrusted Jira ticket title text. A malicious or
   malformed ticket title (e.g. containing `; rm -rf .;`) could execute arbitrary shell
   commands.

## Reliability / Audit-trail integrity

2. **Lost per-step execution log** (`autopilot/infrastructure/agents/code_executor.py`)
   `execute()` builds a per-step `execution_log` list (tracking success/failure/output
   per plan step) but never returns or persists it. The Tester and RunRecord never see
   which specific plan step failed.

3. **Brittle file-extraction heuristic** (`autopilot/infrastructure/agents/code_executor.py`)
   `_extract_modified_files` parses OpenCode's free-text stdout for line prefixes like
   `"Modified:"`, `"Created:"` — likely to under- or over-report modified files depending
   on OpenCode's actual output format.

4. **Silent state-persistence failures** (`autopilot/application/orchestrator/engine.py`)
   `_serialize_state` wraps everything in `except Exception: pass`. If persistence fails,
   it fails silently, undermining the resume/audit-trail guarantees the ledger design
   depends on.

5. **Unchecked git command sequencing** (`autopilot/infrastructure/agents/publisher.py`)
   `_execute_git_workflow` runs checkout → pull → branch → commit → push sequentially
   without checking `_git_cmd`'s boolean return before proceeding. A failed checkout
   still lets branch/commit/push continue on the wrong base branch.

6. **Wrong branch restore on error** (`autopilot/infrastructure/persistence/ledger_committer.py`)
   `commitledger`'s exception handler runs `checkout "-"` (toggle to previous branch)
   instead of the explicitly saved `current` branch — can strand the repo on
   `autopilot-results` after a failure.

## Concurrency / Config validation

7. **No atomic/locked JSON writes** (`autopilot/infrastructure/persistence/ledger.py`,
   `run_record_store.py`) — plain `open()`/`json.dump()` with no file locking or
   atomic temp-file+rename. Concurrent runs or a crash mid-write can corrupt the files.

8. **No upfront config validation for most CLI commands** (`autopilot/cli/commands.py`,
   `autopilot/infrastructure/bootstrap.py`) — only `work` calls `validate_environment`.
   `config`, `ledger`, and `resume` call `create_application()` directly, so a
   misconfigured `vault_location`/`workspace_location` produces a cryptic error instead
   of a clear message.

## Test coverage gaps

9. No test files exist for `engine.py`, `graph_builder.py`, `retry_policy.py`,
   `bootstrap.py`, or any of the 7 agents (code_executor, publisher, tester, planner,
   context_builder, documentation, reviewer) — despite ~176 tests existing for other
   modules. This leaves the retry loop, state merge, and conditional routing logic
   (the most complex code in the project) unverified.

10. No `test_ledger_committer.py` — the stateful branch-switching/restore logic
    (item 6 above) is unverified.

## Architecture / Tech debt

11. **Dead wiring for ReviewerAgent** (`autopilot/infrastructure/bootstrap.py`,
    `graph_builder.py`) — `ReviewerAgent` is instantiated/registered on every startup
    but has no graph node (`NODE_AGENT_MAP` doesn't include it) and
    `build_review_graph()` raises `NotImplementedError`.

12. **Misleading "success" on Jira no-op** (`autopilot/infrastructure/agents/publisher.py`)
    `_update_jira` returns `{"skipped": False, "note": "...not yet implemented..."}` —
    reads as a successful update in metrics even though nothing happened.

13. **Redundant/overly broad exception handling** (`autopilot/infrastructure/agents/publisher.py`)
    `_load_rules` catches `(KeyError, Exception)` — redundant since `Exception` already
    covers `KeyError` — and silently swallows any Obsidian tool failure.

14. **Overly broad retry classification** (`autopilot/application/orchestrator/retry_policy.py`)
    Any exception not explicitly listed as retryable is classified `NON_RETRYABLE` —
    conflates genuine agent bugs (e.g. `AttributeError`) with legitimate non-retryable
    business errors (auth/config), pausing the workflow the same way for both.

## Missing features / Doc-vs-reality gaps

15. **Disconnected stub layers** (`autopilot/cli/commands.py`) — `status`/`review` CLI
    commands are hardcoded print stubs, disconnected from separate
    `StatusCommand`/`ReviewCommand` use-case stub classes that already exist in
    `application/use_cases/`.

16. **README documents Jira transition capability that Publisher never uses**
    (`README.md` vs `publisher.py`) — README documents `apply_transition`/`comment`
    and a `jira_transition` workflow rule, but `PublisherAgent` never calls the Jira
    tool (see item 12).

17. README roadmap items may be stale — "Conectar el StructuredLogger a la ejecución
    del grafo" and "Sesiones de OpenCode (--continue)" appear to already be
    implemented in `engine.py` and `opencode_tool.py` respectively. Worth confirming
    against actual runtime behavior.

## Performance

18. `ledger.py`'s `summary()`/`load()` fully re-parse and rebuild the entire ledger on
    every CLI call, with no pagination — fine at current scale, will degrade as the
    ledger grows.

---

## Proposed grouping for implementation

| # | Group | Type | Findings covered |
|---|-------|------|-------------------|
| 1 | Fix shell injection in Publisher | Bugfix | 1, 5 |
| 2 | Fix lost execution evidence & silent persistence failures | Bugfix | 2, 3, 4, 6, 12, 13 |
| 3 | Atomic/locked persistence + upfront config validation | Feature | 7, 8 |
| 4 | Test coverage for engine/graph_builder/retry_policy/agents | Feature | 9, 10 |

Deferred (not part of initial implementation pass, tracked here for visibility):
- 11 (dead ReviewerAgent wiring), 14 (retry classification nuance), 15 (status/review
  stub consolidation), 16/17 (doc accuracy), 18 (ledger pagination).
