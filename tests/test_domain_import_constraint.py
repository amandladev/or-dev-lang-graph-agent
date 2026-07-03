"""Property 19: Domain layer import constraint.

Validates: Requirements 10.2, 10.6

For any Python module in the domain package, the module's import statements
SHALL reference only the Python standard library or other modules within the
domain package — never the application or infrastructure packages.
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
DOMAIN_PACKAGE_DIR = PROJECT_ROOT / "autopilot" / "domain"

# Collect all .py files under autopilot/domain/
DOMAIN_MODULES: list[Path] = sorted(DOMAIN_PACKAGE_DIR.rglob("*.py"))

# Known Python standard library top-level module names (3.11+).
# We build this from sys.stdlib_module_names which is available in Python 3.10+.
STDLIB_MODULE_NAMES: frozenset[str] = frozenset(sys.stdlib_module_names)

# Forbidden top-level packages for domain modules
FORBIDDEN_PACKAGES = {"autopilot.application", "autopilot.infrastructure"}


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
    """Check if an import is allowed in the domain layer.

    Allowed imports:
    - Python standard library modules
    - Modules within autopilot.domain
    """
    # Standard library check: get top-level package name
    top_level = module_name.split(".")[0]
    if top_level in STDLIB_MODULE_NAMES:
        return True

    # Domain-internal imports are allowed
    if module_name == "autopilot.domain" or module_name.startswith("autopilot.domain."):
        return True

    # Everything else is forbidden
    return False


def _violates_forbidden_packages(module_name: str) -> bool:
    """Check if the import directly references forbidden packages."""
    for forbidden in FORBIDDEN_PACKAGES:
        if module_name == forbidden or module_name.startswith(forbidden + "."):
            return True
    return False


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

# We need at least one module to sample from
assert len(DOMAIN_MODULES) > 0, (
    "No Python modules found in autopilot/domain/. "
    "Ensure the domain package exists before running tests."
)


@settings(max_examples=100)
@given(module_path=st.sampled_from(DOMAIN_MODULES))
def test_domain_module_imports_only_stdlib_or_domain(module_path: Path):
    """**Validates: Requirements 10.2, 10.6**

    Property 19: For any Python module in the domain package, all import
    statements reference only the Python standard library or other modules
    within the domain package.
    """
    imports = _get_imports(module_path)
    for imp in imports:
        assert _is_allowed_import(imp), (
            f"Domain module {module_path.relative_to(PROJECT_ROOT)} "
            f"has disallowed import: '{imp}'. "
            f"Domain modules may only import from stdlib or autopilot.domain.*"
        )


@settings(max_examples=100)
@given(module_path=st.sampled_from(DOMAIN_MODULES))
def test_domain_module_does_not_import_application_or_infrastructure(module_path: Path):
    """**Validates: Requirements 10.2, 10.6**

    Property 19: No module in the domain package has import statements
    referencing the autopilot.application or autopilot.infrastructure packages.
    """
    imports = _get_imports(module_path)
    for imp in imports:
        assert not _violates_forbidden_packages(imp), (
            f"Domain module {module_path.relative_to(PROJECT_ROOT)} "
            f"imports from forbidden package: '{imp}'. "
            f"Domain modules must not reference autopilot.application or "
            f"autopilot.infrastructure."
        )
