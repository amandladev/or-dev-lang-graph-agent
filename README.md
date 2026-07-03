# Autopilot

Sistema local de orquestación de flujos de trabajo para desarrolladores. Autopilot coordina agentes especializados y herramientas para automatizar el ciclo completo de desarrollo — desde la toma de tickets hasta la implementación, testing, documentación y publicación.

Autopilot **no es** un asistente de código. Es un orquestador que coordina herramientas existentes (OpenCode, Playwright, Jira, etc.) mediante una arquitectura basada en agentes, ejecutándose completamente en macOS sin dependencias de infraestructura cloud.

## Arquitectura

El proyecto sigue principios de **Clean Architecture** con tres capas bien definidas:

```
autopilot/
├── domain/          # Entidades, value objects e interfaces (sin dependencias externas)
├── application/     # Casos de uso, orquestador y registros
├── infrastructure/  # Implementaciones concretas: agentes, herramientas, adaptadores
├── cli/             # Interfaz de línea de comandos (Click)
└── config.yaml      # Plantilla de configuración por defecto
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

## Instalación

```bash
# Clonar el repositorio
git clone <repo-url>
cd or-dev-langchain-agent

# Instalar en modo desarrollo
pip install -e ".[dev]"
```

## Configuración

Copia la plantilla de configuración al directorio raíz del proyecto:

```bash
cp autopilot/config.yaml config.yaml
```

Edita `config.yaml` y establece los campos requeridos:

```yaml
vault_location: "/ruta/a/tu/vault/obsidian"
workspace_location: "/ruta/a/tu/workspace"
llm_model: "gpt-4"
llm_provider: "openai"
```

Todos los campos soportan override por variable de entorno con el patrón `AUTOPILOT_<FIELD_NAME>`:

```bash
export AUTOPILOT_LLM_MODEL="claude-3-opus"
export AUTOPILOT_TIMEOUT_SECONDS=120
```

## Uso

```bash
# Ejecutar un workflow completo para un ticket
autopilot work TICKET-123

# Ver la configuración actual
autopilot config

# Resumir un workflow pausado o fallido
autopilot resume

# Ver estado del workflow activo (stub en MVP)
autopilot status

# Iniciar un workflow de revisión (stub en MVP)
autopilot review
```

También se puede ejecutar como módulo:

```bash
python -m autopilot work TICKET-123
```

## Agentes

| Agente | Responsabilidad |
|--------|----------------|
| Context_Builder | Obtiene detalles del ticket y contexto relacionado |
| Planner | Crea un plan de implementación estructurado |
| Code_Executor | Implementa cambios de código según el plan |
| Tester | Ejecuta tests y validaciones |
| Publisher | Publica resultados y actualiza el ticket |
| Documentation_Agent | Genera documentación del trabajo realizado |
| Reviewer | Revisa archivos modificados (workflow de review) |

> En el MVP solo el **Planner** tiene lógica implementada. Los demás son stubs que levantan `NotImplementedError`.

## Herramientas

| Herramienta | Descripción |
|-------------|-------------|
| filesystem | Operaciones de lectura/escritura/listado de archivos |
| jira | Interacción con Jira (stub) |
| git | Operaciones Git (stub) |
| github | Interacción con GitHub (stub) |
| obsidian | Búsqueda en vault Obsidian (stub) |
| playwright | Automatización de navegador (stub) |
| opencode | Agente de código LLM (stub) |

> En el MVP solo **filesystem** tiene implementación funcional.

## Manejo de errores

- **Errores retryables** (timeout, red, tests fallidos): reintentos automáticos con backoff exponencial
- **Errores no retryables** (autenticación, configuración, schema): pausa inmediata del workflow
- El estado se persiste después de cada nodo exitoso para permitir resumir

## Tests

```bash
# Ejecutar toda la suite
pytest

# Ejecutar con output verbose
pytest -v

# Ejecutar solo tests de propiedades
pytest tests/test_*_constraint.py tests/test_agent_registry.py tests/test_tool_registry.py tests/test_serialization_roundtrip.py tests/test_config_validation.py tests/test_env_var_override.py tests/test_input_extraction.py tests/test_state_merge.py
```

La suite incluye **107 tests**:
- Tests de propiedades (Hypothesis) validando invariantes arquitectónicos y de correctitud
- Tests unitarios para serialización, logger, herramientas y casos de uso
- Tests de integración end-to-end del CLI

## Estructura del proyecto

```
autopilot/
├── __init__.py
├── __main__.py                    # Entry point: python -m autopilot
├── config.yaml                    # Plantilla de configuración
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
    ├── agents/                    # PlannerAgent + 6 stubs
    ├── tools/                     # FilesystemTool + 6 stubs
    ├── adapters/                  # JSONSerializer, YAMLConfigLoader, StructuredLogger
    └── bootstrap.py               # Cableado de dependencias (DI)
```

## Estado del MVP

Este es el **MVP Foundation** — establece la arquitectura completa con correctitud verificada:

- ✅ Clean Architecture con restricciones de importación validadas por tests
- ✅ Motor de orquestación LangGraph funcional
- ✅ Serialización con round-trip verificado por property testing
- ✅ Sistema de configuración con validación y overrides por env vars
- ✅ Manejo de errores con clasificación y retry automático
- ✅ CLI funcional con 5 comandos
- ✅ Bootstrap con inyección de dependencias completa

**Próximos pasos:** Implementar la lógica real de cada agente y herramienta (stubs → implementaciones completas).

## Licencia

Proyecto privado.
