"""Small, deterministic conflict analysis for planned ticket changes."""

from typing import Any


class ConflictDetector:
    """Compare planner manifests without imposing a scheduling policy."""

    def analyze(self, plans: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Return overlapping files/modules and declared dependencies."""
        ticket_ids = list(plans)
        overlaps: list[dict[str, Any]] = []
        dependencies: list[dict[str, Any]] = []
        for index, left_id in enumerate(ticket_ids):
            left = plans[left_id] or {}
            left_files = set(left.get("expected_files", []))
            left_modules = set(left.get("affected_modules", []))
            for right_id in ticket_ids[index + 1:]:
                right = plans[right_id] or {}
                files = sorted(left_files & set(right.get("expected_files", [])))
                modules = sorted(left_modules & set(right.get("affected_modules", [])))
                if files or modules:
                    overlaps.append({
                        "tickets": [left_id, right_id],
                        "files": files,
                        "modules": modules,
                        "recommendation": "review_or_sequence",
                    })

            for dependency in left.get("depends_on", []):
                if dependency in plans:
                    dependencies.append({"ticket": left_id, "depends_on": dependency})

        return {
            "parallel_safe": not overlaps and not dependencies,
            "overlaps": overlaps,
            "dependencies": dependencies,
        }
