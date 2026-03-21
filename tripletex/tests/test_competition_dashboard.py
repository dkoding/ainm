from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.competition_dashboard import build_competition_dashboard


class CompetitionDashboardTests(unittest.TestCase):
    def test_dashboard_is_ready_when_coverage_and_verification_pass(self) -> None:
        dashboard = build_competition_dashboard(
            coverage_report={
                "contract_version": "tripletex.task_analysis.v1",
                "method_count": 82,
                "coded_method_count": 25,
                "wrapper_only_method_count": 57,
                "unsupported_method_count": 0,
                "documented_task_category_coverage": {"employees": True},
                "documented_task_category_gaps": [],
            },
            verification={
                "compile": {"passed": True},
                "tests": {"passed": True, "tests_run": 38},
            },
        )

        self.assertTrue(dashboard["release_gate"]["ready"])
        self.assertEqual(dashboard["test_status"]["tests_run"], 38)
        self.assertTrue(dashboard["language_coverage"]["German"])
        self.assertTrue(dashboard["attachment_coverage"]["pdf"])

    def test_dashboard_is_blocked_when_gaps_or_failures_exist(self) -> None:
        dashboard = build_competition_dashboard(
            coverage_report={
                "contract_version": "tripletex.task_analysis.v1",
                "method_count": 82,
                "coded_method_count": 25,
                "wrapper_only_method_count": 57,
                "unsupported_method_count": 0,
                "documented_task_category_coverage": {"employees": False},
                "documented_task_category_gaps": ["employees"],
            },
            verification={
                "compile": {"passed": False},
                "tests": {"passed": False, "tests_run": 12},
            },
        )

        self.assertFalse(dashboard["release_gate"]["ready"])
        self.assertGreaterEqual(len(dashboard["release_gate"]["reasons"]), 2)


if __name__ == "__main__":
    unittest.main()
