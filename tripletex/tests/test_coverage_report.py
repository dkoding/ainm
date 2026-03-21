from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.coverage_report import build_coverage_report


class CoverageReportTests(unittest.TestCase):
    def test_runtime_coverage_report_has_expected_sections(self) -> None:
        report = build_coverage_report()

        self.assertIn("contract_version", report)
        self.assertIn("documented_task_category_coverage", report)
        self.assertIn("methods", report)
        self.assertIn("resource_capabilities", report)
        self.assertIn("resource_support_matrix", report)
        self.assertTrue(report["methods"])
        self.assertTrue(report["resource_capabilities"])
        self.assertTrue(report["resource_support_matrix"])
        self.assertTrue(any(item["deterministic_execution_supported"] for item in report["resource_support_matrix"]))

    def test_generated_coverage_report_file_matches_runtime_shape(self) -> None:
        report_path = Path(__file__).resolve().parents[1] / "coverage_report.json"
        data = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertIn("documented_task_category_coverage", data)
        self.assertIn("methods", data)
        self.assertIn("resource_capabilities", data)
        self.assertIn("resource_support_matrix", data)
        self.assertTrue(any(item["resource_family"] == "project" for item in data["resource_capabilities"]))
        self.assertTrue(any(item["resource_family"] == "project" for item in data["resource_support_matrix"]))


if __name__ == "__main__":
    unittest.main()
