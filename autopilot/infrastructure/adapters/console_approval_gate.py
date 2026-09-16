"""Console-based approval gate implementation.

Prompts the user on the terminal for human-in-the-loop checkpoints.
Auto-approves when the gate is not configured or when stdin is not a
TTY (so automation/CI is never blocked).
"""

import sys
from typing import Any

from autopilot.domain.entities.config import Config


class ConsoleApprovalGate:
    """Approval gate that prompts on the console and respects config.

    A gate only prompts when it is listed in Config.approvals AND the
    process has an interactive stdin. In any other case it approves
    silently (non-configured gate) or with a warning (non-TTY stdin).
    """

    def __init__(self, config: Config) -> None:
        """Initialize the console approval gate.

        Args:
            config: Application configuration with the approvals list.
        """
        self._config = config
        self._skip_all = False

    def skip_all(self, skip: bool) -> None:
        """Set whether all approval prompts are bypassed.

        Used by the CLI --yes flag to run unattended.

        Args:
            skip: True to auto-approve every gate.
        """
        self._skip_all = skip

    def require(self, gate_name: str, details: dict[str, Any] | None = None) -> bool:
        """Request approval for a gate, prompting when required.

        Args:
            gate_name: Identifier of the gate (e.g. "plan").
            details: Contextual information to display (e.g. the plan).

        Returns:
            True if approved (or not required), False if rejected.
        """
        if gate_name not in self._config.approvals or self._skip_all:
            return True

        if not sys.stdin.isatty():
            print(
                f"  ⚠ Approval gate '{gate_name}' requires a human, but stdin "
                "is not interactive — auto-approving.",
                file=sys.stderr,
            )
            return True

        self._render_details(details)
        try:
            answer = input(f"  Approve {gate_name}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")

    @staticmethod
    def _render_details(details: dict[str, Any] | None) -> None:
        """Print the contextual details for the gate in a readable form.

        Args:
            details: Contextual information to display.
        """
        if not details:
            return
        plan = details.get("plan")
        if isinstance(plan, dict) and plan.get("steps"):
            print("\n  Plan:")
            for step in plan["steps"]:
                description = str(step.get("description", "")).strip()
                if description:
                    print(f"    {step.get('step', '?')}. {description[:160]}")
        for key in ("files", "tests"):
            value = details.get(key)
            if isinstance(value, list) and value:
                print(f"\n  {key.capitalize()}:")
                for item in value[:20]:
                    print(f"    • {str(item)[:120]}")
        print()