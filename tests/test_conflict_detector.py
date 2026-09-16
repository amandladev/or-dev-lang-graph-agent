"""Tests for lightweight planner conflict analysis."""

from autopilot.application.conflicts import ConflictDetector


def test_detects_overlapping_files_and_modules():
    report = ConflictDetector().analyze({
        "WPD-619": {"expected_files": ["src/payment/service.py"], "affected_modules": ["src/payment"]},
        "WPD-620": {"expected_files": ["src/user/service.py"], "affected_modules": ["src/user"]},
        "WPD-621": {"expected_files": ["src/payment/service.py"], "affected_modules": ["src/payment"]},
    })

    assert report["parallel_safe"] is False
    assert report["overlaps"] == [{
        "tickets": ["WPD-619", "WPD-621"],
        "files": ["src/payment/service.py"],
        "modules": ["src/payment"],
        "recommendation": "review_or_sequence",
    }]


def test_declared_dependency_marks_plan_not_parallel_safe():
    report = ConflictDetector().analyze({
        "WPD-620": {"depends_on": ["WPD-619"]},
        "WPD-619": {},
    })

    assert report["parallel_safe"] is False
    assert report["dependencies"] == [{"ticket": "WPD-620", "depends_on": "WPD-619"}]
