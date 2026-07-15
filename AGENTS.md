# AGENTS.md — Contexto del Proyecto Autopilot

> Este archivo proporciona contexto esencial sobre el proyecto para que los agentes de IA
> puedan trabajar eficientemente sin necesidad de explorar el codebase completo en cada iteración.

## Qué es Autopilot

Autopilot es un **sistema local de orquestación de flujos de trabajo** para desarrolladores.
Coordina agentes especializados para automatizar el ciclo completo de desarrollo:
ticket → implementación → tests → commit → documentación.

**NO es** un asistente de código. Es un orquestador que ejecuta herramientas existentes.

## Stack tecnológico

- **Lenguaje:** Python 3.11+
- **Orquestación:** LangGraph StateGraph
- **CLI:** Click
- **Config:** YAML con env var overrides
- **Testing:** pytest + Hypothesis (property-based)
- **Persistencia:** JSON files + git branch `autopilot-results`

## Arquitectura

```
autopilot/
├── domain/          # Entidades, value objects, interfaces (SIN dependencias externas)
├── application/     # Casos de uso, orquestador, registros
├── infrastructure/  # Implementaciones: agentes, tools, adapters, persistencia
└── cli/             # Click CLI
```

**Regla de dependencias:** Infrastructure → Application → Domain (hacia adentro).

## Flujo principal

```
autopilot work TICKET-ID
    ↓
WorkCommand.execute()
    ↓
OrchestrationEngine.execute(graph, state, run_record)
    ↓
Grafo: Context_Builder → Planner → Code_Executor → Tester → Publisher → Documentation
    ↓
RunRecord guardado → Ledger entry → Git commit a branch autopilot-results
```

## Archivos clave

| Archivo | Propósito |
|---------|-----------|
| `infrastructure/bootstrap.py` | DI wiring — crea todas las dependencias |
| `application/orchestrator/engine.py` | Motor de ejecución con retry y RunRecord |
| `application/orchestrator/graph_builder.py` | Construye grafos LangGraph |
| `application/use_cases/work_command.py` | Caso de uso principal |
| `domain/entities/workflow_state.py` | Estado compartido en el grafo |
| `domain/entities/run_record.py` | Registro de ejecución (schema completo) |
| `domain/entities/ledger_entry.py` | Entrada del ledger de auditoría |
| `infrastructure/persistence/run_record_store.py` | CRUD para run records |
| `infrastructure/persistence/ledger.py` | Ledger central de auditoría |
| `infrastructure/persistence/ledger_committer.py` | Git commit del ledger |
| `infrastructure/tools/jira_tool.py` | Cliente Jira extendido |
| `cli/commands.py` | Comandos CLI |

## Agentes

| Agente | Input | Output |
|--------|-------|--------|
| Context_Builder | ticket_id | context (ticket data + vault notes) |
| Planner | ticket, context, metadata | plan (pasos estructurados) |
| Code_Executor | plan, context | modified_files, evidence |
| Tester | modified_files, context | evidence (test results) |
| Publisher | modified_files, context | — |
| Documentation_Agent | all state | — |

## Tools

| Tool | Acciones |
|------|----------|
| JiraTool | get_ticket, get_transitions, apply_transition, comment, create_subtask, search_jql, status_entered_at |
| OpenCodeTool | execute (opencode run) |
| ObsidianTool | search |
| FilesystemTool | read, write, list |

## Configuración

```yaml
# ~/.autopilot.yaml
vault_location: "/path/to/obsidian/vault"
# workspace_location se auto-detecta del CWD (no configurar)
llm_model: "anthropic/claude-sonnet-4-20250514"
llm_provider: "anthropic"
timeout_seconds: 300
max_retries: 3
verbosity: normal  # quiet | normal | verbose
```

Env vars: `JIRA_<INSTANCE>_URL`, `JIRA_<INSTANCE>_EMAIL`, `JIRA_<INSTANCE>_TOKEN`
Override: `AUTOPILOT_WORKSPACE_LOCATION` (forzar workspace específico)

## Persistencia

### Run Records
- Ubicación: `{workspace}/runs/{run_id}/run-record.json`
- Uno por ejecución
- Contiene: status, verdict, tests, logs, errors, evidence, metrics

### Ledger
- Ubicación: `{workspace}/ledger.json`
- Central, idempotente por run_id
- Se commitea a branch `autopilot-results`

## Comandos CLI

```bash
autopilot work TICKET-ID          # Ejecutar workflow
autopilot work TICKET-ID --dry-run  # Sin cambios reales
autopilot resume                   # Resumir workflow pausado
autopilot config                   # Ver configuración
autopilot ledger                   # Ver resumen de ejecuciones
autopilot ledger --ticket TICKET   # Ver ejecuciones de un ticket
```

## Testing

```bash
python3 -m pytest                  # Todos los tests (176)
python3 -m pytest -v               # Verbose
python3 -m pytest tests/test_run_record.py  # Tests específicos
```

## Convenciones

1. **Sin comentarios** en el código a menos que el usuario los pida explícitamente
2. **Clean Architecture**: domain no importa de infrastructure
3. **Type hints** en todas las funciones públicas
4. **Dataclasses** para entidades y value objects
5. **ToolResult** como retorno de tools (success, data, error)
6. **RunRecord** se crea al inicio y se actualiza durante la ejecución

## Errores conocidos

- `git_tool.py`, `github_tool.py`, `playwright_tool.py` son stubs (NotImplementedError)
- `ReviewerAgent` es stub
- `status` y `review` commands son stubs
- OpenCode sessions no mantienen contexto entre pasos (cada paso es stateless)
- LedgerCommitter requiere que el workspace sea un repositorio git (si no, skip silencioso)

## Contexto del usuario

- Proyecto personal de automatización de workflow de desarrollo
- También trabaja en un agente de QA automatizado en producción: `/Users/sergioreyes/Documents/dfx5/wts/dfx5-pe-qa-agent`
- Se extrajo patrones del QA agent: Jira Client extendido, Run Records, Ledger
- Vault de Obsidian en: `/Users/sergioreyes/Documents/sergio/obsidian/wts-vault`
