# Contribuir a Autopilot

Guía rápida de convenciones del proyecto para cualquier colaborador (humano o agente).

## Arquitectura — regla de dependencias

El proyecto sigue Clean Architecture con tres capas:

```
domain/          # Entidades, value objects, interfaces. CERO dependencias externas.
application/     # Casos de uso, orquestador, registros. Depende solo de domain/.
infrastructure/  # Agentes, tools, adapters, persistencia. Implementa las interfaces de domain/.
cli/             # Click CLI. Puede depender de cualquier capa (es la capa más externa).
```

**Regla:** las dependencias siempre apuntan hacia adentro
(`infrastructure` → `application` → `domain`). `domain/` nunca importa de
`application/` ni de `infrastructure/`; `application/` nunca importa de
`infrastructure/`. Esto está verificado por
[tests/test_domain_import_constraint.py](tests/test_domain_import_constraint.py) y
[tests/test_application_import_constraint.py](tests/test_application_import_constraint.py) —
si tu cambio los rompe, estás importando en la dirección equivocada.

## Convenciones de código

1. **Sin comentarios** en el código a menos que se pidan explícitamente (las
   funciones/clases públicas sí llevan docstrings).
2. **Type hints** en todas las funciones públicas.
3. **Dataclasses** para entidades y value objects.
4. **`ToolResult`** como tipo de retorno uniforme para todas las tools
   (`success`, `data`, `error`).
5. Nuevas dependencias externas van en `domain/interfaces/` como Protocol/ABC
   antes de implementarse en `infrastructure/`.

## Tests

```bash
python3 -m pytest -q          # toda la suite
python3 -m pytest -v tests/test_archivo.py   # un archivo específico
```

- Los tests que ejercitan operaciones de git (`Path.cwd()`-dependientes, ver
  `code_executor.py`/`ledger_committer.py`) deben usar `monkeypatch.chdir(tmp_path)`
  con un repo git real, no mockear `subprocess` directamente.
- Property-based tests con Hypothesis se usan para invariantes de persistencia
  (ver `tests/test_atomic_write.py`, `tests/test_ledger_lock.py`).
- Cualquier cambio en `domain/` o `application/` que agregue un import nuevo
  debe correr `test_domain_import_constraint.py`/`test_application_import_constraint.py`
  para confirmar que no rompe la regla de dependencias.

## Linters (opcional, recomendado)

Si tenés `ruff` instalado (`pip install -e ".[dev]"` lo incluye):

```bash
ruff check autopilot tests
ruff format --check autopilot tests
```

## Pull requests / cambios

- Un cambio de comportamiento en un agente/tool debe venir acompañado de un
  test que lo cubra.
- Si el cambio toca `README.md`, mantené la sección de
  [Roadmap](README.md#roadmap--qué-falta-para-mejorar) sincronizada (mover
  ítems de "pendiente" a "ya implementado" cuando corresponda).
- No introduzcas nombres de clientes/empresas reales en ejemplos de
  documentación — usá prefijos genéricos (`PROJ-123`, `ACME-456`, etc.).
