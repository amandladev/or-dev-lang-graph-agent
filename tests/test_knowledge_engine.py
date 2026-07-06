"""Tests for the Knowledge Engine components.

Tests:
- Experience entity
- SearchCriteria value object
- ExperienceBuilder
- JsonKnowledgeEngine (store, find_similar, find_by_ticket, find_by_tags, search)
"""

import tempfile
import json
from datetime import datetime
from pathlib import Path

import pytest

from autopilot.domain.entities.experience import Experience
from autopilot.domain.value_objects.search_criteria import SearchCriteria
from autopilot.domain.interfaces.knowledge_engine import KnowledgeEngineInterface
from autopilot.application.knowledge.experience_builder import ExperienceBuilder
from autopilot.infrastructure.knowledge.json_knowledge_engine import JsonKnowledgeEngine


# ---------------------------------------------------------------------------
# Experience entity tests
# ---------------------------------------------------------------------------


class TestExperience:
    def test_create_minimal_experience(self):
        exp = Experience(id="1", ticket_id="CULQI-100", objective="Fix payment bug")
        assert exp.id == "1"
        assert exp.ticket_id == "CULQI-100"
        assert exp.objective == "Fix payment bug"
        assert exp.tags == []
        assert exp.modified_files == []

    def test_searchable_text_combines_fields(self):
        exp = Experience(
            objective="Implement refund flow",
            summary="Added refund endpoint",
            functional_domain="payments",
            solution_description="Created POST /refunds endpoint",
            tags=["refund", "api"],
            technologies=["python", "fastapi"],
            patterns_applied=["repository pattern"],
            decisions=["Use async handlers"],
            services_affected=["payment-service"],
        )
        text = exp.searchable_text()
        assert "refund" in text
        assert "payments" in text
        assert "python" in text
        assert "fastapi" in text
        assert "repository pattern" in text
        assert "payment-service" in text

    def test_searchable_text_empty_experience(self):
        exp = Experience()
        assert exp.searchable_text() == ""


# ---------------------------------------------------------------------------
# SearchCriteria tests
# ---------------------------------------------------------------------------


class TestSearchCriteria:
    def test_empty_criteria(self):
        criteria = SearchCriteria()
        assert criteria.is_empty()

    def test_criteria_with_text_not_empty(self):
        criteria = SearchCriteria(text="refund")
        assert not criteria.is_empty()

    def test_criteria_with_tags_not_empty(self):
        criteria = SearchCriteria(tags=["payment"])
        assert not criteria.is_empty()

    def test_criteria_immutable(self):
        criteria = SearchCriteria(text="test", limit=5)
        with pytest.raises(AttributeError):
            criteria.text = "changed"


# ---------------------------------------------------------------------------
# ExperienceBuilder tests
# ---------------------------------------------------------------------------


class TestExperienceBuilder:
    def test_build_from_complete_state(self):
        state = {
            "ticket": {
                "id": "CULQI-200",
                "title": "Implement payment reversal",
                "description": "Add reversal endpoint for POS transactions",
                "labels": ["payment", "pos"],
                "project": "CULQI",
            },
            "plan": {
                "steps": [
                    {"step": 1, "description": "Create reversal handler"},
                    {"step": 2, "description": "Add unit tests"},
                ]
            },
            "context": {},
            "evidence": [
                {"type": "test_result", "description": "pytest", "data": {"status": "passed"}}
            ],
            "modified_files": ["src/handlers/reversal.py", "tests/test_reversal.py"],
            "errors": [],
            "metrics": {},
        }

        builder = ExperienceBuilder()
        exp = builder.build(state)

        assert exp.ticket_id == "CULQI-200"
        assert exp.objective == "Implement payment reversal"
        assert "python" in exp.technologies
        assert exp.result == "success"
        assert len(exp.decisions) == 2
        assert exp.id  # Should have generated a UUID

    def test_build_infers_technologies_from_files(self):
        state = {
            "ticket": {"id": "T-1", "title": "Fix"},
            "plan": {"steps": []},
            "context": {},
            "evidence": [],
            "modified_files": ["src/app.ts", "package.json", "src/utils.js"],
            "errors": [],
            "metrics": {},
        }
        builder = ExperienceBuilder()
        exp = builder.build(state)

        assert "typescript" in exp.technologies
        assert "javascript" in exp.technologies

    def test_build_with_errors_returns_partial_result(self):
        state = {
            "ticket": {"id": "T-2", "title": "Feature"},
            "plan": {"steps": [{"step": 1, "description": "Do stuff"}]},
            "context": {},
            "evidence": [],
            "modified_files": [],
            "errors": [{"description": "Connection timeout"}],
            "metrics": {},
        }
        builder = ExperienceBuilder()
        exp = builder.build(state)

        assert exp.result == "partial"
        assert "Connection timeout" in exp.problems_encountered

    def test_build_infers_domain_from_labels(self):
        state = {
            "ticket": {"id": "T-3", "title": "Fix payment bug", "labels": ["payment"]},
            "plan": {"steps": []},
            "context": {},
            "evidence": [],
            "modified_files": [],
            "errors": [],
            "metrics": {},
        }
        builder = ExperienceBuilder()
        exp = builder.build(state)

        assert exp.functional_domain == "payments"


# ---------------------------------------------------------------------------
# JsonKnowledgeEngine tests
# ---------------------------------------------------------------------------


class TestJsonKnowledgeEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        return JsonKnowledgeEngine(storage_dir=str(tmp_path))

    def test_implements_protocol(self, engine):
        assert isinstance(engine, KnowledgeEngineInterface)

    def test_store_creates_json_file(self, engine, tmp_path):
        exp = Experience(
            id="test-001",
            ticket_id="CULQI-100",
            objective="Test experience",
            tags=["test"],
        )
        result_id = engine.store(exp)

        assert result_id == "test-001"
        filepath = tmp_path / "experiences" / "test-001.json"
        assert filepath.exists()

        data = json.loads(filepath.read_text())
        assert data["ticket_id"] == "CULQI-100"
        assert data["objective"] == "Test experience"

    def test_store_generates_id_if_empty(self, engine):
        exp = Experience(ticket_id="X-1", objective="No ID")
        result_id = engine.store(exp)
        assert result_id  # Non-empty
        assert len(result_id) > 10  # UUID-like

    def test_find_by_ticket(self, engine):
        engine.store(Experience(id="a", ticket_id="CULQI-100", objective="First"))
        engine.store(Experience(id="b", ticket_id="CULQI-200", objective="Second"))

        found = engine.find_by_ticket("CULQI-200")
        assert found is not None
        assert found.objective == "Second"

    def test_find_by_ticket_not_found(self, engine):
        engine.store(Experience(id="a", ticket_id="CULQI-100", objective="Only one"))
        assert engine.find_by_ticket("NONEXISTENT") is None

    def test_find_by_tags(self, engine):
        engine.store(Experience(id="a", ticket_id="T-1", tags=["payment", "refund"]))
        engine.store(Experience(id="b", ticket_id="T-2", tags=["auth", "login"]))
        engine.store(Experience(id="c", ticket_id="T-3", tags=["payment", "charge"]))

        results = engine.find_by_tags(["payment"])
        assert len(results) == 2
        assert all("payment" in r.tags for r in results)

    def test_find_by_tags_or_logic(self, engine):
        engine.store(Experience(id="a", tags=["python"]))
        engine.store(Experience(id="b", tags=["javascript"]))
        engine.store(Experience(id="c", tags=["rust"]))

        results = engine.find_by_tags(["python", "javascript"])
        assert len(results) == 2

    def test_find_similar_by_text(self, engine):
        engine.store(Experience(
            id="a", objective="Implement payment refund", tags=["payment"],
            technologies=["python"], functional_domain="payments",
        ))
        engine.store(Experience(
            id="b", objective="Add user authentication", tags=["auth"],
            technologies=["python"], functional_domain="auth",
        ))
        engine.store(Experience(
            id="c", objective="Fix payment charge timeout", tags=["payment"],
            technologies=["typescript"], functional_domain="payments",
        ))

        criteria = SearchCriteria(text="payment refund", domain="payments", limit=5)
        results = engine.find_similar(criteria)

        # Payment-related experiences should rank higher
        assert len(results) >= 2
        assert results[0].id == "a"  # Exact text + domain match

    def test_find_similar_by_technology(self, engine):
        engine.store(Experience(id="a", objective="Task A", technologies=["python", "fastapi"]))
        engine.store(Experience(id="b", objective="Task B", technologies=["typescript", "express"]))

        criteria = SearchCriteria(technologies=["python", "fastapi"])
        results = engine.find_similar(criteria)

        assert len(results) == 1
        assert results[0].id == "a"

    def test_find_similar_empty_criteria_returns_empty(self, engine):
        engine.store(Experience(id="a", objective="Something"))
        results = engine.find_similar(SearchCriteria())
        assert results == []

    def test_search_full_text(self, engine):
        engine.store(Experience(id="a", objective="payment reversal implementation"))
        engine.store(Experience(id="b", objective="user login flow"))

        results = engine.search("reversal")
        assert len(results) == 1
        assert results[0].id == "a"

    def test_search_respects_limit(self, engine):
        for i in range(20):
            engine.store(Experience(id=f"exp-{i}", objective=f"Task {i} about payments"))

        results = engine.search("payments", limit=5)
        assert len(results) == 5

    def test_round_trip_serialization(self, engine):
        original = Experience(
            id="rt-001",
            ticket_id="CULQI-999",
            objective="Round trip test",
            summary="Testing persistence",
            functional_domain="testing",
            repositories=["my-repo"],
            services_affected=["svc-a"],
            modified_files=["src/main.py"],
            technologies=["python"],
            patterns_applied=["singleton"],
            decisions=["Use dataclass"],
            problems_encountered=["Import error"],
            solution_description="Fixed the import",
            tests_executed=["pytest"],
            result="success",
            tags=["test", "python"],
            created_at=datetime(2024, 6, 15, 10, 30, 0),
        )

        engine.store(original)
        loaded = engine.find_by_ticket("CULQI-999")

        assert loaded is not None
        assert loaded.id == original.id
        assert loaded.ticket_id == original.ticket_id
        assert loaded.objective == original.objective
        assert loaded.technologies == original.technologies
        assert loaded.tags == original.tags
        assert loaded.modified_files == original.modified_files
        assert loaded.result == original.result
