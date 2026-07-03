"""Property 20: Application layer import constraint.

Validates: Requirements 10.3, 10.7

For any Python module in the application package, the module's import statements
SHALL reference only the Python standard library, autopilot.domain, or other modules
within autopilot.application — never the infrastructure package.
"""

import ast
import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APPLICATION_PACKAGE_DIR = PROJECT_ROOT / "autopilot" / "application"

# Collect all .py files under autopilot/application/
APPLICATION_MODULES: list[Path] = sorted(APPLICATION_PACKAGE_DIR.rglob("*.py"))

# Known Python standard library top-level module names (3.10+).
STDLIB_MODULE_NAMES: frozenset[str] = frozenset(sys.stdlib_module_names)

# Third-party packages explicitly allowed by the design:
# - langgraph: required for the LangGraph orchestration engine
# - yaml (pyyaml): used by ConfigCommand for YAML presentation
ALLOWED_THIRD_PARTY: frozenset[str] = frozenset({"langgraph", "yaml"})

# Forbidden top-level packages for application modules
FORBIDDEN_PACKAGES = {"autopilot.infrastructure"}


def _get_imports(filepath: Path) -> list[str]:
    """Parse a Python file and return all imported module names."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _is_allowed_import(module_name: str) -> bool:
    """Check if an import is allowed in the application layer.

    Allowed imports:
    - Python standard library modules
    - Modules within autopilot.domain
    - Modules within autopilot.application
    - Explicitly allowed third-party packages (langgraph, yaml)
    """
    top_level = module_name.split(".")[0]

    # Standard library check
    if top_level in STDLIB_MODULE_NAMES:
        return True

    # Domain imports are allowed
    if module_name == "autopilot.domain" or module_name.startswith("autopilot.domain."):
        return True

    # Application-internal imports are allowed
    if module_name == "autopilot.application" or module_name.startswith("autopilot.application."):
        return True

    # Allowed third-party packages
    if top_level in ALLOWED_THIRD_PARTY:
        return True

    # Everything else is forbidden
    return False


def _violates_forbidden_packages(module_name: str) -> bool:
    """Check if the import directly references the infrastructure package."""
    for forbidden in FORBIDDEN_PACKAGES:
        if module_name == forbidden or module_name.startswith(forbidden + "."):
            return True
    return False


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

# We need at least one module to sample from
assert len(APPLICATION_MODULES) > 0, (
    "No Python modules found in autopilot/application/. "
    "Ensure the application package exists before running tests."
)


@settings(max_examples=100)
@given(module_path=st.sampled_from(APPLICATION_MODULES))
def test_application_module_imports_only_allowed_sources(module_path: Path):
    """**Validates: Requirements 10.3, 10.7**

    Property 20: For any Python module in the application package, all import
    statements reference only the Python standard library, autopilot.domain,
    other modules within autopilot.application, or explicitly allowed
    third-party packages (langgraph, yaml).
    """
    imports = _get_imports(module_path)
    for imp in imports:
        assert _is_allowed_import(imp), (
            f"Application module {module_path.relative_to(PROJECT_ROOT)} "
            f"has disallowed import: '{imp}'. "
            f"Application modules may only import from stdlib, "
            f"autopilot.domain.*, autopilot.application.*, or "
            f"allowed third-party packages ({', '.join(sorted(ALLOWED_THIRD_PARTY))})."
        )


@settings(max_examples=100)
@given(module_path=st.sampled_from(APPLICATION_MODULES))
def test_application_module_does_not_import_infrastructure(module_path: Path):
    """**Validates: Requirements 10.3, 10.7**

    Property 20: No module in the application package has import statements
    referencing the autopilot.infrastructure package.
    """
    imports = _get_imports(module_path)
    for imp in imports:
        assert not _violates_forbidden_packages(imp), (
            f"Application module {module_path.relative_to(PROJECT_ROOT)} "
            f"imports from forbidden package: '{imp}'. "
            f"Application modules must not reference autopilot.infrastructure."
        )
