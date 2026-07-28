# Autopilot

Sistema local de orquestación de flujos de trabajo para desarrolladores. Autopilot coordina agentes especializados y herramientas para automatizar el ciclo completo de desarrollo — desde la toma de tickets hasta la implementación, testing, documentación y publicación.

Autopilot **no es** un asistente de código. Es un orquestador que coordina herramientas existentes (OpenCode, Jira, Git, etc.) mediante una arquitectura basada en agentes, ejecutándose completamente en macOS sin dependencias de infraestructura cloud.

## Índice

- [Quick Start](#quick-start)
- [Arquitectura](#arquitectura)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Configuración](#configuración)
- [Uso — Referencia de comandos](#uso)
- [Agentes](#agentes)
- [Herramientas](#herramientas)
- [Persistencia y Auditoría](#persistencia-y-auditoría)
- [Manejo de errores](#manejo-de-errores)
- [Solución de problemas](#solución-de-problemas)
- [Tests](#tests)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Roadmap](#roadmap--qué-falta-para-mejorar)

## Quick Start

Para alguien que ya tiene `opencode` instalado y quiere correr su primer ticket:

```bash
# 1. Instalar autopilot (una sola vez)
cd or-dev-langchain-agent
pip3 install -e .

# 2. Crear config global (una sola vez)
cp autopilot/.autopilot.yaml.template ~/.autopilot.yaml
# Edita ~/.autopilot.yaml: vault_location, llm_model, llm_provider

# 3. Exportar credenciales de Jira para la instancia del ticket
#    (el prefijo del ticket define la instancia: PROJ-123 -> JIRA_PROJ_*)
export JIRA_PROJ_URL="https://tu-dominio.atlassian.net"
export JIRA_PROJ_EMAIL="tu@email.com"
export JIRA_PROJ_TOKEN="tu-api-token"

# 4. Pararte en el repo del proyecto que quieres modificar
cd /ruta/a/tu/proyecto

# 5. Correr en dry-run primero para validar el entorno sin tocar nada
autopilot work PROJ-123 --dry-run

# 6. Si todo se ve bien, correr en modo real
autopilot work PROJ-123
```

Si algo falla en el paso 5/6, revisa [Solución de problemas](#solución-de-problemas) —
`autopilot work` valida el entorno antes de arrancar y explica qué falta.

## Arquitectura

El proyecto sigue principios de **Clean Architecture** con tres capas bien definidas:

```
autopilot/
├── domain/          # Entidades, value objects e interfaces (sin dependencias externas)
├── application/     # Casos de uso, orquestador y registros
├── infrastructure/  # Implementaciones concretas: agentes, herramientas, adaptadores, persistencia
├── cli/             # Interfaz de línea de comandos (Click)
└── .autopilot.yaml.template  # Plantilla de configuración
```

**Motor de orquestación:** LangGraph StateGraph — modela los workflows como grafos dirigidos donde cada nodo es un agente especializado.

**Patrón de inyección:** Constructor injection, cableado en un módulo bootstrap centralizado.

**Flujo de datos:** Un objeto `WorkflowState` compartido fluye a través del grafo, acumulando datos conforme cada agente contribuye su salida.

**Auditoría:** Run Records + Ledger para tracking completo de ejecuciones con persistencia en git.

### Grafo de trabajo

```
START → Context_Builder → Planner → Code_Executor → Tester → Publisher → Documentation_Agent → END
                                                        ↑                |
                                                        └── retry ───────┘ (si error retryable)
```

## Requisitos

- Python 3.11+
- macOS (diseñado para ejecución local)
- [OpenCode](https://github.com/opencode-ai/opencode) instalado y configurado

## Instalación

```bash
# Clonar el repositorio
git clone <repo-url>
cd or-dev-langchain-agent

# Instalar globalmente (recomendado)
pip3 install -e .

# O instalar en modo desarrollo
pip install -e ".[dev]"
```

Después de instalar, el comando `autopilot` estará disponible globalmente.

## Configuración

### Config global (una sola vez)

```bash
cp autopilot/.autopilot.yaml.template ~/.autopilot.yaml
```

Edita `~/.autopilot.yaml`:

```yaml
vault_location: "/Users/tu-usuario/ruta/a/tu/vault"
llm_model: "anthropic/claude-sonnet-4-20250514"
llm_provider: "anthropic"
```

**Nota:** `workspace_location` se auto-detecta del directorio donde ejecutas `autopilot`. No es necesario configurarlo.

El loader busca config en este orden:
1. `.autopilot.yaml` en el directorio actual (override por proyecto)
2. `~/.autopilot.yaml` en tu home (config global)

### Variables de entorno — Jira

```bash
# Una instancia por cada proyecto/dominio
export JIRA_PROJ_URL="https://tu-dominio.atlassian.net"
export JIRA_PROJ_EMAIL="tu@email.com"
export JIRA_PROJ_TOKEN="tu-api-token"

export JIRA_ACME_URL="https://otro-dominio.atlassian.net"
export JIRA_ACME_EMAIL="tu@email.com"
export JIRA_ACME_TOKEN="otro-token"
```

La instancia se infiere automáticamente del prefijo del ticket (PROJ-123 → JIRA_PROJ_*).

### Reglas de workflow (vault)

Crea `.autopilot-rules.md` en la raíz de tu vault de Obsidian:

```markdown
# Workflow Rules

- branch_from: develop
- branch_pattern: feature/{ticket_id}
- commit_pattern: feat({ticket_id}): {description}
- jira_transition: In Progress -> Code Review
- push_remote: origin
```

Si no existe este archivo, se usan reglas por defecto. También busca reglas en notas sueltas como fallback.

**Nota:** `jira_transition` se lee y se refleja en las métricas del run (`metrics.jira_update`),
pero el Publisher **todavía no llama la API de Jira** para aplicar la transición ni postear
comentarios — `_update_jira` reporta `{"skipped": true}` de forma explícita. Usa
`autopilot ledger`/el run record para confirmar el estado real; no asumas que el ticket
cambió de status solo porque configuraste la regla.

### Override por variable de entorno

Todos los campos del config soportan override:

```bash
export AUTOPILOT_TIMEOUT_SECONDS=120
export AUTOPILOT_MAX_RETRIES=5
export AUTOPILOT_VERBOSITY=verbose
```

## Uso

```bash
# Desde cualquier directorio de proyecto
cd /tu/proyecto

# Ejecutar workflow completo para un ticket
autopilot work PROJ-123

# Ejecutar en modo dry-run (sin cambios reales)
autopilot work PROJ-123 --dry-run

# Ver la configuración cargada
autopilot config

# Resumir un workflow pausado o fallido
autopilot resume

# Ver el ledger de ejecuciones
autopilot ledger

# Ver ejecuciones de un ticket específico
autopilot ledger --ticket PROJ-123

# Ver estado (stub)
autopilot status

# Review workflow (stub)
autopilot review
```

### Referencia de comandos y flags

| Comando | Flags | Descripción |
|---------|-------|-------------|
| `autopilot work TICKET_ID` | `--dry-run` · `--skip-validation` · `--config-path` | Ejecuta el workflow completo (Context_Builder → Planner → Code_Executor → Tester → Publisher → Documentation_Agent) para `TICKET_ID`. Valida config y entorno antes de arrancar salvo `--skip-validation`. `--dry-run` no hace commits/push reales. |
| `autopilot resume` | `--config-path` | Reanuda el último workflow pausado o fallido desde el último nodo completado con éxito (usa `.autopilot_state.json`). |
| `autopilot config` | `--config-path` | Imprime en YAML la configuración efectiva (tras merge de defaults + archivo + env vars). Útil para depurar qué config se está usando realmente. |
| `autopilot ledger` | `--ticket TICKET_ID` · `--limit N` · `--config-path` | Muestra el resumen del ledger de auditoría. Con `--ticket` filtra por ticket; `--limit` acota cuántas entradas se listan (las estadísticas totales siempre son sobre el ledger completo). |
| `autopilot status` | — | Stub — todavía no implementado. |
| `autopilot review` | — | Stub — todavía no implementado. |

`--config-path` (default `auto`) acepta una ruta explícita a un `.autopilot.yaml`; si se omite, se
autodescubre siguiendo el orden descrito en [Configuración](#configuración).

## Agentes

| Agente | Qué hace |
|--------|----------|
| **Context_Builder** | Fetch ticket de Jira + busca notas relevantes en vault Obsidian |
| **Planner** | Envía contexto a OpenCode y genera un plan de implementación estructurado |
| **Code_Executor** | Ejecuta cada paso del plan via `opencode run` |
| **Tester** | Detecta tipo de proyecto (Node/Python) y ejecuta tests automáticamente |
| **Publisher** | Lee reglas del vault, crea rama, commit, push según convenciones del proyecto |
| **Documentation_Agent** | Genera resumen markdown del trabajo realizado |
| **Reviewer** | Workflow de revisión de código (pendiente) |

## Herramientas

| Herramienta | Descripción |
|-------------|-------------|
| **opencode** | Ejecuta prompts via `opencode run` (modo batch) |
| **jira** | REST API v2/v3 de Atlassian — fetch, transitions, comments, subtasks, JQL search |
| **obsidian** | Búsqueda por keywords en vault local (scoring por relevancia) |
| **filesystem** | Operaciones de lectura/escritura/listado de archivos |
| git | Operaciones Git via subprocess (stub — Publisher lo hace directo) |
| github | Interacción con GitHub API (pendiente) |
| playwright | Automatización de navegador (pendiente) |

### Jira Tool — Acciones disponibles

| Acción | Descripción |
|--------|-------------|
| `get_ticket` | Obtener detalles del ticket (resumen, descripción, estado, labels, comments) |
| `get_transitions` | Listar transiciones disponibles para el ticket |
| `apply_transition` | Aplicar una transición por nombre (case-insensitive) |
| `comment` | Postear un comment (auto-convierte Markdown a wiki markup) |
| `create_subtask` | Crear un sub-task bajo un ticket padre |
| `search_jql` | Buscar issues usando JQL |
| `status_entered_at` | Obtener timestamp de la última entrada a un status (para idempotencia) |

## Persistencia y Auditoría

### Run Records

Cada ejecución produce un **RunRecord** que captura el ciclo completo:

- **Identidad:** run_id, ticket_id, ticket_title
- **Temporal:** started_at, finished_at, duration_seconds
- **Resultado:** status (running/completed/failed/cancelled), verdict (PASS/FAIL/BLOCKED)
- **Contenido:** plan ejecutado, archivos modificados, tests (executed/passed/failed)
- **Auditoría:** logs, errors, evidence, tokens_used, cost_usd

**Nota:** `tokens_used`/`cost_usd` están en el schema para una futura integración,
pero ningún agente/tool actual reporta uso de tokens u costo de vuelta al engine —
en la práctica siempre quedan en `null`. No los uses como fuente real de costos todavía.

Ubicación: `{workspace}/runs/{run_id}/run-record.json`

### Ledger

El **Ledger** es el registro central de auditoría. Cada ejecución agrega una entrada:

- Idempotente por run_id (re-ejecutar reemplaza la entrada)
- Summary Markdown offline sin necesidad de Jira
- Historial por ticket

Ubicación: `{workspace}/ledger.json`

### Git Persistence

El ledger se commitea a una branch dedicada `autopilot-results` para:

- Historial de versiones de todas las ejecuciones
- Diff entre runs
- Acceso offline a datos históricos
- Patrón single-writer para concurrencia

### Detección automática de tests

El Tester detecta el framework según los archivos del proyecto:

| Archivo encontrado | Framework | Comando |
|---|---|---|
| `package.json` con jest | Jest | `npm test` |
| `package.json` con mocha | Mocha | `npm test` |
| `package.json` con vitest | Vitest | `npx vitest run` |
| `pyproject.toml` | Pytest | `python3 -m pytest --tb=short` |
| `Makefile` con target test | Make | `make test` |

## Manejo de errores

- **Errores retryables** (timeout, red, tests fallidos): reintentos automáticos con backoff exponencial
- **Errores no retryables** (autenticación, configuración, schema): pausa inmediata del workflow
- El estado se persiste después de cada nodo exitoso para permitir resumir con `autopilot resume`

## Solución de problemas

Mensajes comunes al correr `autopilot work`/`resume`/`config`/`ledger` y cómo resolverlos:

| Mensaje / síntoma | Causa | Solución |
|---|---|---|
| `workspace_location must not be empty` / `vault_location must not be empty` | El config no tiene esos campos completos (`config_sanity_validator`, corre antes que nada) | Completa `vault_location` en `~/.autopilot.yaml`. `workspace_location` se auto-detecta del CWD; no lo dejes vacío a mano si lo overrideaste. |
| `workspace_location is not creatable: ...` | La ruta configurada no existe y ninguna carpeta ancestro es escribible | Usa una ruta bajo un directorio con permisos de escritura, o crea el directorio manualmente. |
| `opencode not found in PATH` | El binario `opencode` no está instalado o no está en el `PATH` | Instala [OpenCode](https://github.com/opencode-ai/opencode) y verifica con `which opencode`. |
| `Vault directory not found: ...` | `vault_location` apunta a una carpeta que no existe | Corrige la ruta en `~/.autopilot.yaml` (debe ser la raíz de tu vault de Obsidian). |
| `Jira credentials incomplete for instance 'X'` (warning) | Faltan `JIRA_X_URL` / `JIRA_X_EMAIL` / `JIRA_X_TOKEN` para el prefijo del ticket (ej. `PROJ-123` → instancia `PROJ`) | Exporta las tres variables de entorno para esa instancia. Sin ellas, Context_Builder simplemente omite el fetch de Jira (no bloquea el run). |
| El comando corre pero nunca crea/pushea una rama | Estás corriendo `--dry-run`, o `.autopilot-rules.md` no define reglas válidas | Quita `--dry-run` para un run real; revisa que `.autopilot-rules.md` exista en la raíz del vault con el formato esperado (ver [Reglas de workflow](#reglas-de-workflow-vault)). |
| El ticket no cambia de status en Jira aunque configuré `jira_transition` | Publisher todavía no implementa la llamada real a la API de Jira para transitions | Comportamiento esperado por ahora — ver la nota en [Reglas de workflow](#reglas-de-workflow-vault) y el roadmap. Aplica la transición manualmente en Jira. |
| `Not a git repository, skipping ledger commit` (log) | El `workspace_location` no es un repo git | No es un error bloqueante: el ledger sigue guardándose en `ledger.json`, solo se salta el commit a `autopilot-results`. Inicializa un repo git ahí si quieres ese historial versionado. |
| `autopilot resume` falla con `State file not found: ...` | No existe `.autopilot_state.json` en el workspace (ningún run previo persistió estado) | Corre `autopilot work TICKET_ID` primero; `resume` solo aplica a workflows que fallaron o se pausaron a mitad de camino. |
| Cambié `~/.autopilot.yaml` pero no veo el efecto | Existe un `.autopilot.yaml` en el directorio del proyecto (override local) que tiene prioridad | Revisa `autopilot config` para ver qué archivo se cargó realmente, o borra/ajusta el override local. |

Si el mensaje no está en esta tabla, corre con `--config-path` explícito y sin `--skip-validation`
para obtener el diagnóstico más detallado posible antes de reportarlo.

## Tests

```bash
# Ejecutar toda la suite
python3 -m pytest

# Con output verbose
python3 -m pytest -v

# Solo tests de un componente
python3 -m pytest tests/test_jira_markdown.py -v
python3 -m pytest tests/test_run_record.py -v
python3 -m pytest tests/test_ledger.py -v
```

Suite: **319 tests** (property tests + unit + integración).

## Estructura del proyecto

```
autopilot/
├── __init__.py
├── __main__.py                    # Entry point: python -m autopilot
├── .autopilot.yaml.template       # Plantilla de configuración
├── cli/
│   └── commands.py                # Comandos CLI (Click)
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
    └── bootstrap.py               # Cableado de dependencias (DI)
```

## Roadmap — Qué falta para mejorar

### Ya implementado (verificado en código, no en el roadmap original)

- [x] **Sesiones de OpenCode**: `OpenCodeTool` usa `--continue` para mantener contexto entre pasos (`opencode_tool.py`)
- [x] **Logging real en terminal**: `StructuredLogger` está conectado a `OrchestrationEngine` (`log_agent_start`/`log_agent_completion`/`log_retry`)
- [x] **Output del workflow más detallado**: `autopilot work` imprime un reporte con archivos modificados, tests, errores y evidencia (`cli/commands.py`)
- [x] **Workspace detection**: `workspace_location` se auto-detecta del CWD en `yaml_config_loader.py` (override vía `AUTOPILOT_WORKSPACE_LOCATION`)

### Prioridad Alta

- [ ] **Validación pre-ejecución**: Verificar que opencode, git, y las credenciales están disponibles antes de iniciar (parcial: `validate_environment`/`config_sanity_validator` ya corren antes de `work`/`resume`/`config`/`ledger`, falta cubrir disponibilidad real del binario `opencode`)
- [ ] **Jira transition real**: Publisher lee `jira_transition` pero no llama la API de Jira todavía (`_update_jira` siempre reporta `skipped`) — ver nota en "Reglas de workflow"

### Prioridad Media

- [ ] **PR automático**: Publisher crea un PR en GitHub/GitLab después del push
- [ ] **Reviewer agent**: Análisis de código pre-merge via OpenCode (agente y comando `review` son stubs conectados pero sin implementar; ver `ReviewCommand`/`build_review_graph`)
- [ ] **Playwright tests**: Integrar tests E2E para proyectos con frontend
- [ ] **Multiple config merge**: Config global + config por proyecto (override específico)
- [ ] **Failure diagnostics**: Usar LLM para generar diagnósticos de fallos para operadores

### Prioridad Baja

- [ ] **Memory/RAG**: Usar ejecuciones anteriores como contexto para mejorar planes futuros
- [ ] **Parallel execution**: Ejecutar pasos independientes del plan en paralelo
- [ ] **Web UI**: Dashboard para ver estado de workflows activos
- [ ] **Plugin system**: Permitir agregar agentes y herramientas custom sin modificar el core
- [ ] **Métricas y analytics**: Tiempo por agente, tasa de éxito, tokens consumidos

## Licencia

Proyecto privado. Ver [LICENSE](LICENSE).
