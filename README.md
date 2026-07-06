# Autopilot

Sistema local de orquestación de flujos de trabajo para desarrolladores. Autopilot coordina agentes especializados y herramientas para automatizar el ciclo completo de desarrollo — desde la toma de tickets hasta la implementación, testing, documentación y publicación.

Autopilot **no es** un asistente de código. Es un orquestador que coordina herramientas existentes (OpenCode, Jira, Git, etc.) mediante una arquitectura basada en agentes, ejecutándose completamente en macOS sin dependencias de infraestructura cloud.

## Arquitectura

El proyecto sigue principios de **Clean Architecture** con tres capas bien definidas:

```
autopilot/
├── domain/          # Entidades, value objects e interfaces (sin dependencias externas)
├── application/     # Casos de uso, orquestador y registros
├── infrastructure/  # Implementaciones concretas: agentes, herramientas, adaptadores
├── cli/             # Interfaz de línea de comandos (Click)
└── .autopilot.yaml.template  # Plantilla de configuración
```

**Motor de orquestación:** LangGraph StateGraph — modela los workflows como grafos dirigidos donde cada nodo es un agente especializado.

**Patrón de inyección:** Constructor injection, cableado en un módulo bootstrap centralizado.

**Flujo de datos:** Un objeto `WorkflowState` compartido fluye a través del grafo, acumulando datos conforme cada agente contribuye su salida.

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

# Instalar en modo desarrollo
pip install -e ".[dev]"

# Agregar al PATH (si pip lo instala fuera del PATH)
export PATH="$HOME/Library/Python/3.13/bin:$PATH"
```

## Configuración

### Config global (una sola vez)

```bash
cp autopilot/.autopilot.yaml.template ~/.autopilot.yaml
```

Edita `~/.autopilot.yaml`:

```yaml
vault_location: "/Users/tu-usuario/ruta/a/tu/vault"
workspace_location: "/Users/tu-usuario/Documents/workspace"
llm_model: "anthropic/claude-sonnet-4-20250514"
llm_provider: "anthropic"
```

El loader busca config en este orden:
1. `.autopilot.yaml` en el directorio actual (override por proyecto)
2. `~/.autopilot.yaml` en tu home (config global)

### Variables de entorno — Jira

```bash
# Una instancia por cada proyecto/dominio
export JIRA_CULQI_URL="https://tu-dominio.atlassian.net"
export JIRA_CULQI_EMAIL="tu@email.com"
export JIRA_CULQI_TOKEN="tu-api-token"

export JIRA_WTS_URL="https://otro-dominio.atlassian.net"
export JIRA_WTS_EMAIL="tu@email.com"
export JIRA_WTS_TOKEN="otro-token"
```

La instancia se infiere automáticamente del prefijo del ticket (CULQI-123 → JIRA_CULQI_*).

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
python3 -m autopilot work CULQI-123

# Ver la configuración cargada
python3 -m autopilot config

# Resumir un workflow pausado o fallido
python3 -m autopilot resume

# Ver estado (stub)
python3 -m autopilot status

# Review workflow (stub)
python3 -m autopilot review
```

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
| **jira** | REST API v3 de Atlassian — fetch tickets, multi-instancia |
| **obsidian** | Búsqueda por keywords en vault local (scoring por relevancia) |
| **filesystem** | Operaciones de lectura/escritura/listado de archivos |
| git | Operaciones Git via subprocess (stub — Publisher lo hace directo) |
| github | Interacción con GitHub API (pendiente) |
| playwright | Automatización de navegador (pendiente) |

## Detección automática de tests

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

## Tests

```bash
# Ejecutar toda la suite
python3 -m pytest

# Con output verbose
python3 -m pytest -v

# Solo property tests
python3 -m pytest tests/test_*_constraint.py tests/test_agent_registry.py tests/test_tool_registry.py tests/test_serialization_roundtrip.py tests/test_config_validation.py tests/test_env_var_override.py tests/test_input_extraction.py tests/test_state_merge.py
```

Suite: **108 tests** (property tests + unit + integración).

## Estructura del proyecto

```
autopilot/
├── __init__.py
├── __main__.py                    # Entry point: python -m autopilot
├── .autopilot.yaml.template       # Plantilla de configuración
├── cli/
│   └── commands.py                # Comandos CLI (Click)
├── domain/
│   ├── entities/                  # WorkflowState, Ticket, Plan, Config
│   ├── value_objects/             # ErrorRecord, LogEntry, EvidenceItem, Metrics, Exceptions
│   └── interfaces/                # AgentInterface, ToolInterface, SerializerInterface
├── application/
│   ├── orchestrator/              # OrchestrationEngine, GraphBuilder, RetryPolicy
│   ├── registries/                # AgentRegistry, ToolRegistry
│   └── use_cases/                 # WorkCommand, ResumeCommand, ConfigCommand
└── infrastructure/
    ├── agents/                    # ContextBuilder, Planner, CodeExecutor, Tester, Publisher, Documentation
    ├── tools/                     # OpenCode, Jira, Obsidian, Filesystem + stubs
    ├── adapters/                  # JSONSerializer, YAMLConfigLoader, StructuredLogger
    └── bootstrap.py               # Cableado de dependencias (DI)
```

## Roadmap — Qué falta para mejorar

### Prioridad Alta

- [ ] **Sesiones de OpenCode**: Usar `--continue` para mantener contexto entre pasos del Code_Executor (actualmente cada paso es stateless)
- [ ] **Jira transitions reales**: Implementar la API de transiciones de Jira para cambiar status automáticamente
- [ ] **Logging real en terminal**: Conectar el StructuredLogger a la ejecución del grafo para ver progreso en tiempo real (`[Context_Builder] fetching ticket...`, `[Planner] generating plan...`)
- [ ] **Validación pre-ejecución**: Verificar que opencode, git, y las credenciales están disponibles antes de iniciar el workflow
- [ ] **Output del workflow más detallado**: Mostrar resumen final con archivos modificados, rama creada, tests pasados

### Prioridad Media

- [ ] **PR automático**: Publisher crea un PR en GitHub/GitLab después del push
- [ ] **Reviewer agent**: Análisis de código pre-merge via OpenCode
- [ ] **Playwright tests**: Integrar tests E2E para proyectos con frontend
- [ ] **Workspace detection**: Auto-detectar el `workspace_location` del directorio actual en vez de requerirlo en config
- [ ] **Multiple config merge**: Config global + config por proyecto (`.autopilot.yaml` local overridea campos específicos del global)
- [ ] **Dry-run mode**: Ejecutar el workflow sin hacer cambios reales (mostrar qué haría)

### Prioridad Baja

- [ ] **Memory/RAG**: Usar ejecuciones anteriores como contexto para mejorar planes futuros
- [ ] **Parallel execution**: Ejecutar pasos independientes del plan en paralelo
- [ ] **Web UI**: Dashboard para ver estado de workflows activos
- [ ] **Plugin system**: Permitir agregar agentes y herramientas custom sin modificar el core
- [ ] **Métricas y analytics**: Tiempo por agente, tasa de éxito, tokens consumidos

## Licencia

Proyecto privado.
