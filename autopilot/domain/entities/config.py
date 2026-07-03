"""Config entity with validation constraints."""

from dataclasses import dataclass, field


@dataclass
class Config:
    """Application configuration with validated constraints."""

    vault_location: str
    workspace_location: str
    available_mcps: list[str] = field(default_factory=list)
    llm_model: str = ""
    llm_provider: str = ""
    timeout_seconds: int = 60
    max_retries: int = 3
    base_delay: float = 2.0
    backoff_multiplier: float = 2.0
    verbosity: str = "normal"

    def __post_init__(self) -> None:
        """Validate configuration constraints after initialization."""
        self.validate()

    def validate(self) -> None:
        """Enforce all configuration constraints.

        Raises:
            ValueError: If any field violates its constraint, indicating the
                field name, provided value, and expected constraint.
        """
        if len(self.available_mcps) > 20:
            raise ValueError(
                f"available_mcps: got {len(self.available_mcps)} entries, "
                f"expected maximum 20"
            )

        if len(self.llm_model) > 100:
            raise ValueError(
                f"llm_model: got {len(self.llm_model)} characters, "
                f"expected maximum 100"
            )

        if len(self.llm_provider) > 50:
            raise ValueError(
                f"llm_provider: got {len(self.llm_provider)} characters, "
                f"expected maximum 50"
            )

        if not (1 <= self.timeout_seconds <= 600):
            raise ValueError(
                f"timeout_seconds: got {self.timeout_seconds}, "
                f"expected range [1, 600]"
            )

        if not (0 <= self.max_retries <= 10):
            raise ValueError(
                f"max_retries: got {self.max_retries}, "
                f"expected range [0, 10]"
            )

        valid_verbosity = {"quiet", "normal", "verbose"}
        if self.verbosity not in valid_verbosity:
            raise ValueError(
                f"verbosity: got '{self.verbosity}', "
                f"expected one of {sorted(valid_verbosity)}"
            )
