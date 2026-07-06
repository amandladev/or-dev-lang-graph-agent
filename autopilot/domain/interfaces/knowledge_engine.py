"""Knowledge Engine interface protocol.

Defines the contract for storing and retrieving Experiences.
Implementations may use JSON files, SQLite, PostgreSQL, vector databases,
or any other persistence mechanism.

This interface is completely independent of LangGraph, the orchestrator,
and any LLM. It can be used standalone.
"""

from typing import Protocol, runtime_checkable

from autopilot.domain.entities.experience import Experience
from autopilot.domain.value_objects.search_criteria import SearchCriteria


@runtime_checkable
class KnowledgeEngineInterface(Protocol):
    """Protocol for the Knowledge Engine.

    Responsible for persisting Experiences and finding relevant ones
    based on various search strategies.
    """

    def store(self, experience: Experience) -> str:
        """Store an Experience and return its assigned ID.

        If the experience already has an ID, it may be updated or
        a new version created (implementation-dependent).

        Args:
            experience: The Experience entity to persist.

        Returns:
            The ID assigned to the stored experience.
        """
        ...

    def find_similar(self, criteria: SearchCriteria) -> list[Experience]:
        """Find experiences similar to the given criteria.

        The definition of "similar" is implementation-dependent:
        - JSON impl: keyword overlap scoring
        - Vector impl: cosine similarity on embeddings
        - Hybrid: metadata filters + semantic similarity

        Args:
            criteria: What to search for.

        Returns:
            List of matching experiences, ordered by relevance (most relevant first).
            Limited to criteria.limit results.
        """
        ...

    def find_by_ticket(self, ticket_id: str) -> Experience | None:
        """Find the experience associated with a specific ticket.

        Args:
            ticket_id: The ticket identifier (e.g., "CULQI-123").

        Returns:
            The Experience if found, None otherwise.
        """
        ...

    def find_by_tags(self, tags: list[str], limit: int = 10) -> list[Experience]:
        """Find experiences matching any of the given tags.

        Args:
            tags: Tags to match (OR logic — any tag matches).
            limit: Maximum results to return.

        Returns:
            List of matching experiences.
        """
        ...

    def search(self, query: str, limit: int = 10) -> list[Experience]:
        """Full-text search across all experience fields.

        A simpler API for when structured criteria isn't needed.

        Args:
            query: Free-text search query.
            limit: Maximum results to return.

        Returns:
            List of matching experiences, ordered by relevance.
        """
        ...
