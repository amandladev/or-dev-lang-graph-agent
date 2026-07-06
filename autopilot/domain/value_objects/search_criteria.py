"""SearchCriteria value object for knowledge queries.

Encapsulates what the caller wants to find without dictating how to find it.
The implementation of KnowledgeEngine decides the search mechanism.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchCriteria:
    """Criteria for finding similar experiences.

    The caller describes what they're looking for. The KnowledgeEngine
    implementation decides how to interpret these fields:
    - Today (JSON): keyword matching across fields
    - Tomorrow (vector DB): generate embedding from text + filter by metadata

    At least one field should be non-empty for a meaningful search.
    """

    # Free-text describing what to find (objective, problem description)
    text: str = ""

    # Filter by functional domain (e.g., "payments", "auth", "notifications")
    domain: str = ""

    # Filter by technologies (e.g., ["python", "fastapi", "dynamodb"])
    technologies: list[str] = field(default_factory=list)

    # Filter by tags
    tags: list[str] = field(default_factory=list)

    # Filter by services
    services: list[str] = field(default_factory=list)

    # Maximum results to return
    limit: int = 5

    def is_empty(self) -> bool:
        """Check if the criteria has any search terms."""
        return not any([
            self.text,
            self.domain,
            self.technologies,
            self.tags,
            self.services,
        ])
