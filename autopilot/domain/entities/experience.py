"""Experience entity — represents a solved problem and its knowledge.

An Experience captures the useful knowledge from a completed workflow execution.
It is NOT a conversation log or prompt history. It represents what was learned:
the problem, the approach, the solution, and the outcome.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Experience:
    """A solved problem with its accumulated knowledge.

    This entity grows over time. Not all fields need to be populated
    for an Experience to be valid. The minimum is: id, ticket_id,
    objective, and created_at.
    """

    # Identity
    id: str = ""
    ticket_id: str = ""

    # What was the problem
    objective: str = ""
    summary: str = ""
    functional_domain: str = ""

    # Where it happened
    repositories: list[str] = field(default_factory=list)
    services_affected: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)

    # How it was solved
    technologies: list[str] = field(default_factory=list)
    patterns_applied: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    problems_encountered: list[str] = field(default_factory=list)
    solution_description: str = ""

    # What was the outcome
    tests_executed: list[str] = field(default_factory=list)
    result: str = ""  # "success", "partial", "failed"

    # Classification
    tags: list[str] = field(default_factory=list)

    # Temporal
    created_at: datetime = field(default_factory=datetime.now)

    # Extensible metadata (for future fields without schema changes)
    extra: dict[str, Any] = field(default_factory=dict)

    def searchable_text(self) -> str:
        """Produce a single text blob for full-text search.

        Concatenates the most relevant fields into a searchable string.
        Used by search implementations that need a unified text representation
        (keyword matching today, embedding generation tomorrow).

        Returns:
            Concatenated text of the most important fields.
        """
        parts = [
            self.objective,
            self.summary,
            self.functional_domain,
            self.solution_description,
            " ".join(self.tags),
            " ".join(self.technologies),
            " ".join(self.patterns_applied),
            " ".join(self.decisions),
            " ".join(self.services_affected),
        ]
        return " ".join(p for p in parts if p)
