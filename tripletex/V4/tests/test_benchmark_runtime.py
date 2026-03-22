from __future__ import annotations

import base64
import unittest

from app.benchmark import BenchmarkRuntime, FamilyCandidate, FamilyExtraction
from app.contracts import SolveRequest


class StubAttachmentFactExtractor:
    def enrich(self, *, prompt: str, evidence: list[dict[str, object]], attachment_media: list[dict[str, object]]) -> list[dict[str, object]]:
        enriched: list[dict[str, object]] = []
        for item in evidence:
            clone = dict(item)
            clone["documentType"] = "supplier_invoice"
            clone["factSummary"] = "Supplier invoice from ACME AS"
            clone["extractedFactHints"] = ["supplierName=ACME AS", "invoiceNumber=1001"]
            clone["structuredFacts"] = {"supplierName": "ACME AS", "invoiceNumber": "1001"}
            enriched.append(clone)
        return enriched


class StubSelector:
    def __init__(self, candidates: tuple[FamilyCandidate, ...]) -> None:
        self.candidates = candidates

    def select(self, request: object, *, limit: int = 5) -> tuple[FamilyCandidate, ...]:
        return self.candidates[:limit]


class StubSlotExtractor:
    def __init__(self, extraction: FamilyExtraction) -> None:
        self.extraction = extraction

    def extract(self, **_: object) -> FamilyExtraction:
        return self.extraction


class BenchmarkRuntimeTests(unittest.TestCase):
    def test_analysis_uses_selected_family_and_marks_benchmark_candidate(self) -> None:
        runtime = BenchmarkRuntime(
            selector=StubSelector(
                (
                    FamilyCandidate(
                        family_id="timesheet.total_hours",
                        score=9.0,
                        confidence=0.9,
                        matched_terms=(),
                        matched_slots=("startDate", "endDate"),
                        reasons=("Selected by stub selector",),
                    ),
                )
            )
        )
        request = SolveRequest.model_validate(
            {
                "prompt": "How many hours did I work in February 2026?",
                "files": [],
                "tripletex_credentials": {
                    "base_url": "https://example.test/v2",
                    "session_token": "token",
                },
            }
        )

        analysis = runtime.analyze(request)

        self.assertEqual(analysis.selected_family_id, "timesheet.total_hours")
        self.assertTrue(analysis.supported_by_executor)
        self.assertEqual(analysis.execution_mode, "benchmark_candidate")
        self.assertEqual(analysis.selected_route_kind, "raw_operation")
        self.assertEqual(analysis.selected_route_name, "TimesheetEntryTotalHours_getTotalHours")

    def test_prepare_bridge_builds_supplier_invoice_attachment_flow(self) -> None:
        runtime = BenchmarkRuntime(
            selector=StubSelector(
                (
                    FamilyCandidate(
                        family_id="supplier_invoice.import_from_attachment",
                        score=9.0,
                        confidence=0.92,
                        matched_terms=(),
                        matched_slots=("attachment_id",),
                        reasons=("Selected by stub selector",),
                    ),
                )
            ),
            slot_extractor=StubSlotExtractor(
                FamilyExtraction(
                    family_id="supplier_invoice.import_from_attachment",
                    route_kind="flow",
                    route_name="supplier_invoice.import_from_attachment",
                    inputs={"attachment_id": "attachment_1", "description": "Import supplier invoice"},
                    missing_required_inputs=(),
                    warnings=(),
                    confidence=0.95,
                )
            ),
            attachment_fact_extractor=StubAttachmentFactExtractor(),
        )
        request = SolveRequest.model_validate(
            {
                "prompt": "Bookkeep the attached invoice",
                "files": [
                    {
                        "filename": "invoice.txt",
                        "mime_type": "text/plain",
                        "content_base64": base64.b64encode(b"Invoice 1001 from ACME AS").decode("ascii"),
                    }
                ],
                "tripletex_credentials": {
                    "base_url": "https://example.test/v2",
                    "session_token": "token",
                },
            }
        )

        analysis, bridge = runtime.prepare_bridge(
            request,
            current_date="2026-03-22",
            timezone="Europe/Oslo",
            request_id="req_1",
        )

        self.assertIsNotNone(bridge)
        self.assertEqual(analysis.selected_family_id, "supplier_invoice.import_from_attachment")
        self.assertIn("attachments_prepared", analysis.notes)
        self.assertIn("benchmark_bridge_ready", analysis.notes)
        assert bridge is not None
        self.assertEqual(bridge.executionPlan.selectedFlows[0].resolved_name, "supplier_invoice.import_from_attachment")
        self.assertEqual(bridge.executionPlan.selectedFlows[0].inputs["attachment_id"], "attachment_1")


if __name__ == "__main__":
    unittest.main()
