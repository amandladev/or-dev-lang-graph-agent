"""Plan entity."""

from dataclasses import dataclass, field


@dataclass
class Plan:
    """Represents an implementation plan with ordered steps."""

    steps: list[dict] = field(default_factory=list)
    # Each step dict has keys: "description" (str), "agent" (str)
