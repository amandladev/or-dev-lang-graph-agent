"""Pre-execution validators.

Checks that all required external dependencies and credentials are available
before starting a workflow. Fails fast with clear error messages.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ValidationResult:
    """Result of pre-execution validation."""
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_environment(config, ticket_id: str = "") -> ValidationResult:
    """Validate that the environment is ready for workflow execution.

    Checks:
    - OpenCode is installed and in PATH
    - Git is available
    - Jira credentials are set (for the ticket's instance)
    - Vault directory exists
    - Workspace directory exists

    Args:
        config: The loaded Config object.
        ticket_id: Optional ticket ID to check specific Jira instance.

    Returns:
        ValidationResult with errors and warnings.
    """
    result = ValidationResult()

    # Check opencode is available
    if not shutil.which("opencode"):
        result.add_error(
            "opencode not found in PATH. Install it: https://github.com/opencode-ai/opencode"
        )

    # Check git is available
    if not shutil.which("git"):
        result.add_error("git not found in PATH")

    # Check vault directory exists
    vault = Path(config.vault_location)
    if not vault.exists():
        result.add_error(f"Vault directory not found: {config.vault_location}")
    elif not vault.is_dir():
        result.add_error(f"Vault path is not a directory: {config.vault_location}")

    # Check workspace directory exists
    workspace = Path(config.workspace_location)
    if not workspace.exists():
        result.add_warning(
            f"Workspace directory not found: {config.workspace_location} (will be created)"
        )

    # Check Jira credentials for the ticket's instance
    if ticket_id and "-" in ticket_id:
        instance = ticket_id.split("-")[0].upper()
        jira_url = os.environ.get(f"JIRA_{instance}_URL", "")
        jira_email = os.environ.get(f"JIRA_{instance}_EMAIL", "")
        jira_token = os.environ.get(f"JIRA_{instance}_TOKEN", "")

        if not all([jira_url, jira_email, jira_token]):
            missing = []
            if not jira_url:
                missing.append(f"JIRA_{instance}_URL")
            if not jira_email:
                missing.append(f"JIRA_{instance}_EMAIL")
            if not jira_token:
                missing.append(f"JIRA_{instance}_TOKEN")
            result.add_warning(
                f"Jira credentials incomplete for instance '{instance}'. "
                f"Missing: {', '.join(missing)}. "
                f"Context_Builder will skip Jira fetch."
            )

    # Check model configuration
    if config.llm_model and "/" not in config.llm_model:
        result.add_warning(
            f"llm_model '{config.llm_model}' doesn't follow provider/model format "
            f"(e.g., 'anthropic/claude-sonnet-4-20250514'). OpenCode will use its default model."
        )

    return result


def config_sanity_validator(config: Any) -> ValidationResult:
    """Lightweight, fast sanity check of core configuration values.

    Distinct from validate_environment: checks only that workspace_location
    and vault_location are non-blank, and that workspace_location is
    creatable. Does not check opencode/git/Jira availability and does not
    create any directories as a side effect.

    Args:
        config: The loaded Config object.

    Returns:
        ValidationResult with errors and warnings.
    """
    result = ValidationResult()

    workspace = config.workspace_location
    vault = config.vault_location

    if not workspace or not workspace.strip():
        result.add_error("workspace_location must not be empty")

    if not vault or not vault.strip():
        result.add_error("vault_location must not be empty")

    if workspace and workspace.strip():
        creatable, reason = _is_creatable_path(workspace)
        if not creatable:
            result.add_error(f"workspace_location is not creatable: {reason}")

    return result


def _is_creatable_path(path_str: str) -> tuple[bool, str]:
    """Check whether a path either already exists as a directory, or has a
    writable existing ancestor, without creating anything.

    Returns:
        (True, "") if creatable, (False, reason) otherwise.
    """
    path = Path(path_str).expanduser()

    try:
        if path.exists():
            if path.is_dir():
                return True, ""
            return False, f"'{path}' already exists and is not a directory"

        ancestor = path.parent
        while not ancestor.exists():
            parent = ancestor.parent
            if parent == ancestor:
                return False, f"no existing ancestor directory found above '{path}'"
            ancestor = parent

        if not ancestor.is_dir():
            return False, f"ancestor '{ancestor}' exists but is not a directory"

        if not os.access(ancestor, os.W_OK):
            return False, f"ancestor directory '{ancestor}' is not writable"

        return True, ""
    except OSError as exc:
        return False, f"filesystem error while checking '{path}': {exc}"
