"""JSON-based Knowledge Engine implementation.

Persists Experiences as individual JSON files in a local directory.
Search is performed via keyword scoring across experience fields.

This is the MVP implementation. The interface allows replacing this
with SQLite, PostgreSQL, or a vector database without changing
any consumer code (Planner, ExperienceBuilder, CLI).
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from autopilot.domain.entities.experience import Experience
from autopilot.domain.value_objects.search_criteria import SearchCriteria


class JsonKnowledgeEngine:
    """Local JSON file-based Knowledge Engine.

    Stores each Experience as a separate JSON file:
        {storage_dir}/experiences/{id}.json

    Search uses keyword-based scoring on the searchable text of each
    experience. Not optimized for large datasets — designed for
    personal use (hundreds to low thousands of experiences).
    """

    def __init__(self, storage_dir: str) -> None:
        """Initialize the JSON Knowledge Engine.

        Args:
            storage_dir: Base directory for knowledge storage.
                Creates {storage_dir}/experiences/ if it doesn't exist.
        """
        self._storage_dir = Path(storage_dir)
        self._experiences_dir = self._storage_dir / "experiences"
        self._experiences_dir.mkdir(parents=True, exist_ok=True)

    def store(self, experience: Experience) -> str:
        """Store an Experience as a JSON file.

        Args:
            experience: The Experience to persist.

        Returns:
            The ID of the stored experience.
        """
        if not experience.id:
            import uuid
            experience.id = str(uuid.uuid4())

        filepath = self._experiences_dir / f"{experience.id}.json"
        data = self._serialize(experience)
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        return experience.id

    def find_similar(self, criteria: SearchCriteria) -> list[Experience]:
        """Find experiences similar to the given criteria using keyword scoring.

        Scoring strategy:
        - Text match: each keyword from criteria.text found in searchable_text scores 1.0
        - Domain match: exact match scores 5.0
        - Technology overlap: each matching technology scores 3.0
        - Tag overlap: each matching tag scores 2.0
        - Service overlap: each matching service scores 2.0

        Args:
            criteria: Search criteria to match against.

        Returns:
            List of experiences sorted by relevance score, limited to criteria.limit.
        """
        if criteria.is_empty():
            return []

        experiences = self._load_all()
        scored: list[tuple[float, Experience]] = []

        keywords = [w.lower() for w in criteria.text.split() if len(w) > 2]

        for exp in experiences:
            score = self._score_experience(exp, criteria, keywords)
            if score > 0:
                scored.append((score, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for _, exp in scored[:criteria.limit]]

    def find_by_ticket(self, ticket_id: str) -> Experience | None:
        """Find experience by ticket ID.

        Args:
            ticket_id: The ticket identifier.

        Returns:
            The Experience if found, None otherwise.
        """
        for exp in self._load_all():
            if exp.ticket_id == ticket_id:
                return exp
        return None

    def find_by_tags(self, tags: list[str], limit: int = 10) -> list[Experience]:
        """Find experiences matching any of the given tags.

        Args:
            tags: Tags to search for (OR logic).
            limit: Maximum results.

        Returns:
            List of matching experiences.
        """
        tags_lower = {t.lower() for t in tags}
        results = []

        for exp in self._load_all():
            exp_tags = {t.lower() for t in exp.tags}
            if exp_tags & tags_lower:  # Intersection
                results.append(exp)
                if len(results) >= limit:
                    break

        return results

    def search(self, query: str, limit: int = 10) -> list[Experience]:
        """Full-text search across all experience fields.

        Args:
            query: Free-text query.
            limit: Maximum results.

        Returns:
            List of matching experiences sorted by relevance.
        """
        criteria = SearchCriteria(text=query, limit=limit)
        return self.find_similar(criteria)

    def _score_experience(
        self, exp: Experience, criteria: SearchCriteria, keywords: list[str]
    ) -> float:
        """Calculate a relevance score for an experience against criteria.

        Args:
            exp: The experience to score.
            criteria: The search criteria.
            keywords: Pre-computed lowercase keywords from criteria.text.

        Returns:
            Numeric score (higher = more relevant). 0 means no match.
        """
        score = 0.0
        searchable = exp.searchable_text().lower()

        # Text keyword matching
        for kw in keywords:
            if kw in searchable:
                score += 1.0

        # Domain exact match
        if criteria.domain and exp.functional_domain:
            if criteria.domain.lower() == exp.functional_domain.lower():
                score += 5.0

        # Technology overlap
        if criteria.technologies:
            exp_techs = {t.lower() for t in exp.technologies}
            for tech in criteria.technologies:
                if tech.lower() in exp_techs:
                    score += 3.0

        # Tag overlap
        if criteria.tags:
            exp_tags = {t.lower() for t in exp.tags}
            for tag in criteria.tags:
                if tag.lower() in exp_tags:
                    score += 2.0

        # Service overlap
        if criteria.services:
            exp_services = {s.lower() for s in exp.services_affected}
            for svc in criteria.services:
                if svc.lower() in exp_services:
                    score += 2.0

        return score

    def _load_all(self) -> list[Experience]:
        """Load all experiences from the storage directory.

        Returns:
            List of all stored experiences.
        """
        experiences = []
        for filepath in sorted(self._experiences_dir.glob("*.json")):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                exp = self._deserialize(data)
                experiences.append(exp)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue  # Skip malformed files
        return experiences

    def _serialize(self, exp: Experience) -> dict[str, Any]:
        """Serialize an Experience to a JSON-compatible dict."""
        return {
            "id": exp.id,
            "ticket_id": exp.ticket_id,
            "objective": exp.objective,
            "summary": exp.summary,
            "functional_domain": exp.functional_domain,
            "repositories": exp.repositories,
            "services_affected": exp.services_affected,
            "modified_files": exp.modified_files,
            "technologies": exp.technologies,
            "patterns_applied": exp.patterns_applied,
            "decisions": exp.decisions,
            "problems_encountered": exp.problems_encountered,
            "solution_description": exp.solution_description,
            "tests_executed": exp.tests_executed,
            "result": exp.result,
            "tags": exp.tags,
            "created_at": exp.created_at.isoformat(),
            "extra": exp.extra,
        }

    def _deserialize(self, data: dict[str, Any]) -> Experience:
        """Deserialize a dict to an Experience entity."""
        created_at = data.get("created_at", "")
        if isinstance(created_at, str) and created_at:
            created_at = datetime.fromisoformat(created_at)
        else:
            created_at = datetime.now()

        return Experience(
            id=data.get("id", ""),
            ticket_id=data.get("ticket_id", ""),
            objective=data.get("objective", ""),
            summary=data.get("summary", ""),
            functional_domain=data.get("functional_domain", ""),
            repositories=data.get("repositories", []),
            services_affected=data.get("services_affected", []),
            modified_files=data.get("modified_files", []),
            technologies=data.get("technologies", []),
            patterns_applied=data.get("patterns_applied", []),
            decisions=data.get("decisions", []),
            problems_encountered=data.get("problems_encountered", []),
            solution_description=data.get("solution_description", ""),
            tests_executed=data.get("tests_executed", ""),
            result=data.get("result", ""),
            tags=data.get("tags", []),
            created_at=created_at,
            extra=data.get("extra", {}),
        )
