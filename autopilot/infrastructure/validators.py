"""Pre-execution validators.

Checks that all required external dependencies and credentials are available
before starting a workflow. Fails fast with clear error messages.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


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
