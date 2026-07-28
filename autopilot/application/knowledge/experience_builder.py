"""ExperienceBuilder — transforms a completed WorkflowState into an Experience.

This is the sole producer of Experience entities. The Planner only consumes them.
Separation of concerns: the builder knows how to extract knowledge from a workflow,
the Planner knows how to use that knowledge for planning.
"""

import os
import uuid
from datetime import datetime
from typing import Any

from autopilot.domain.entities.experience import Experience


class ExperienceBuilder:
    """Transforms a completed workflow state into a structured Experience.

    Extracts the useful knowledge from the final WorkflowState:
    - What was the problem (from ticket)
    - What was done (from plan + modified files)
    - What was the outcome (from evidence)
    - What can be reused (patterns, technologies, decisions)

    Does NOT use LLMs. Extraction is deterministic from available data.
    Future versions may use LLMs to generate better summaries.
    """

    def build(self, state: dict[str, Any]) -> Experience:
        """Build an Experience from the final workflow state.

        Args:
            state: The final WorkflowState as a dictionary (after all agents completed).

        Returns:
            A populated Experience entity ready to be stored.
        """
        ticket = state.get("ticket", {})
        plan = state.get("plan", {})
        context = state.get("context", {})
        evidence = state.get("evidence", [])
        modified_files = state.get("modified_files", [])
        errors = state.get("errors", [])

        # Extract fields
        ticket_id = ticket.get("id", "")
        objective = ticket.get("title", "")
        description = ticket.get("description", "")

        # Build summary from plan
        summary = self._build_summary(plan, evidence, errors)

        # Infer domain from ticket labels and context
        domain = self._infer_domain(ticket, context)

        # Infer technologies from modified files
        technologies = self._infer_technologies(modified_files)

        # Extract decisions from plan steps
        decisions = self._extract_decisions(plan)

        # Extract problems from errors
        problems = self._extract_problems(errors)

        # Determine result
        result = self._determine_result(evidence, errors)

        # Build tags from various sources
        tags = self._build_tags(ticket, domain, technologies)

        # Infer repository from current directory
        repository = os.path.basename(os.getcwd())

        return Experience(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            objective=objective,
            summary=summary,
            functional_domain=domain,
            repositories=[repository] if repository else [],
            services_affected=self._extract_services(context),
            modified_files=modified_files,
            technologies=technologies,
            patterns_applied=[],  # Future: LLM-extracted
            decisions=decisions,
            problems_encountered=problems,
            solution_description=description,
            tests_executed=self._extract_tests(evidence),
            result=result,
            tags=tags,
            created_at=datetime.now(),
        )

    def _build_summary(self, plan: dict, evidence: list, errors: list) -> str:
        """Build a concise summary of what was accomplished."""
        steps = plan.get("steps", [])
        step_count = len(steps)

        test_results = [e for e in evidence if e.get("type") == "test_result"]
        tests_passed = any(
            e.get("data", {}).get("status") == "passed" for e in test_results
        )

        parts = [f"Executed {step_count} steps."]
        if tests_passed:
            parts.append("Tests passed.")
        if errors:
            parts.append(f"{len(errors)} errors encountered.")

        return " ".join(parts)

    def _infer_domain(self, ticket: dict, context: dict) -> str:
        """Infer the functional domain from ticket metadata."""
        labels = ticket.get("labels", [])

        # Common domain keywords
        domain_keywords = {
            "payments": ["payment", "pago", "cobro", "charge", "refund", "reversal"],
            "auth": ["auth", "login", "session", "token", "credential"],
            "notifications": ["notification", "email", "sms", "push", "alert"],
            "users": ["user", "profile", "account", "registration"],
            "orders": ["order", "cart", "checkout", "purchase"],
            "infrastructure": ["infra", "deploy", "ci", "cd", "pipeline", "docker"],
        }

        text = " ".join(labels + [ticket.get("title", "")]).lower()

        for domain, keywords in domain_keywords.items():
            if any(kw in text for kw in keywords):
                return domain

        return ""

    def _infer_technologies(self, modified_files: list[str]) -> list[str]:
        """Infer technologies from file extensions and paths."""
        techs = set()

        extension_map = {
            ".py": "python",
            ".ts": "typescript",
            ".js": "javascript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".tf": "terraform",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".sql": "sql",
            ".graphql": "graphql",
        }

        path_hints = {
            "lambda": "aws-lambda",
            "serverless": "serverless",
            "docker": "docker",
            "terraform": "terraform",
            "fastapi": "fastapi",
            "express": "express",
            "next": "nextjs",
            "react": "react",
        }

        for filepath in modified_files:
            # Extension-based
            for ext, tech in extension_map.items():
                if filepath.endswith(ext):
                    techs.add(tech)
                    break

            # Path-based
            path_lower = filepath.lower()
            for hint, tech in path_hints.items():
                if hint in path_lower:
                    techs.add(tech)

        return sorted(techs)

    def _extract_decisions(self, plan: dict) -> list[str]:
        """Extract decisions from plan steps."""
        steps = plan.get("steps", [])
        return [s.get("description", "") for s in steps if s.get("description")]

    def _extract_problems(self, errors: list) -> list[str]:
        """Extract problem descriptions from errors."""
        problems = []
        for error in errors:
            if isinstance(error, dict):
                desc = error.get("description", "")
                if desc:
                    problems.append(desc)
        return problems

    def _determine_result(self, evidence: list, errors: list) -> str:
        """Determine the overall result of the workflow."""
        if errors:
            return "partial"

        test_results = [e for e in evidence if e.get("type") == "test_result"]
        if test_results:
            all_passed = all(
                e.get("data", {}).get("status") == "passed" for e in test_results
            )
            return "success" if all_passed else "failed"

        return "success"  # No tests = assume success

    def _build_tags(self, ticket: dict, domain: str, technologies: list[str]) -> list[str]:
        """Build tags from multiple sources."""
        tags = list(ticket.get("labels", []))
        if domain:
            tags.append(domain)
        tags.extend(technologies[:3])  # Top 3 techs as tags

        project = ticket.get("project", "")
        if project:
            tags.append(project.lower())

        return list(set(tags))

    def _extract_services(self, context: dict) -> list[str]:
        """Extract service names from context."""
        # Future: parse context for service references
        return []

    def _extract_tests(self, evidence: list) -> list[str]:
        """Extract test descriptions from evidence."""
        tests = []
        for e in evidence:
            if e.get("type") == "test_result":
                desc = e.get("description", "")
                if desc:
                    tests.append(desc)
        return tests
