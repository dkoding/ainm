from __future__ import annotations

import unittest
from typing import Any

from app.contracts import ExecutionContext, LLMBridgeDocument
from app.raw import RawExecutor, load_raw_catalog
from app.router import BridgeRouter


class RecordingTransport:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        *,
        context: ExecutionContext,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        multipart_data: dict[str, Any] | None = None,
        multipart_files: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params or {},
                "json_body": json_body,
                "multipart_data": multipart_data,
                "multipart_files": multipart_files,
            }
        )
        response = self.responses[(method, path)]
        if callable(response):
            return response(params or {}, json_body or {})
        return response


class RouterExecutionTests(unittest.TestCase):
    def _context(self) -> ExecutionContext:
        return ExecutionContext(
            base_url="https://example.test/v2",
            session_token="token",
            request_id="req-1",
            current_date="2026-03-21",
            timezone="Europe/Oslo",
        )

    def test_router_executes_raw_timesheet_fallback(self) -> None:
        transport = RecordingTransport(
            {
                ("GET", "/timesheet/entry/>totalHours"): {"value": 123.5},
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {
                    "detectedPrimaryLanguage": "nb",
                    "canonicalLanguage": "en",
                    "promptOriginal": "Hei jeg klarer ikke å finne timelisten min, kan du sjekke hvor mange timer jeg jobbet i februar",
                    "promptCanonical": "I cannot find my timesheet. Can you check how many hours I worked in February?",
                },
                "flatBridge": {
                    "fieldBag": {
                        "startDate": "2026-02-01",
                        "endDate": "2026-03-01",
                    },
                    "commandArguments": {
                        "TimesheetEntryTotalHours_getTotalHours": {
                            "startDate": "2026-02-01",
                            "endDate": "2026-03-01",
                        }
                    },
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "name": "timesheet.entry.read",
                            "kind": "technical_flow_family",
                        }
                    ],
                    "selectedCommands": [
                        {
                            "stepId": "step_1",
                            "command": "TimesheetEntryTotalHours_getTotalHours",
                            "commandType": "raw_operation",
                            "operationId": "TimesheetEntryTotalHours_getTotalHours",
                        }
                    ],
                    "stepOrder": ["step_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Hours returned"]},
            }
        )
        result = router.execute(bridge, self._context())
        self.assertEqual(result.traces[0].outputs, {"value": 123.5})
        self.assertEqual(transport.calls[0]["params"], {"startDate": "2026-02-01", "endDate": "2026-03-01"})

    def test_router_executes_customer_create_flow(self) -> None:
        def customer_search(params: dict[str, Any], _body: dict[str, Any]) -> Any:
            self.assertEqual(params["email"], "jason@example.org")
            self.assertEqual(params["customerName"], "Jason Bourne")
            return {"values": []}

        def customer_create(_params: dict[str, Any], body: dict[str, Any]) -> Any:
            self.assertEqual(body["name"], "Jason Bourne")
            self.assertEqual(body["email"], "jason@example.org")
            return {"value": {"id": 7, "name": body["name"], "email": body["email"]}}

        transport = RecordingTransport(
            {
                ("GET", "/customer"): customer_search,
                ("POST", "/customer"): customer_create,
            }
        )
        router = BridgeRouter(raw_executor=RawExecutor(catalog=load_raw_catalog(), transport=transport))
        bridge = LLMBridgeDocument.model_validate(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "flatBridge": {
                    "flowArguments": {
                        "customer.create_or_update": {
                            "name": "Jason Bourne",
                            "email": "jason@example.org",
                            "patch_mode": "auto",
                        }
                    }
                },
                "executionPlan": {
                    "selectedFlows": [
                        {
                            "stepId": "flow_1",
                            "flowName": "customer.create_or_update",
                            "flowType": "business_flow",
                        }
                    ],
                    "stepOrder": ["flow_1"],
                },
                "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
                "completion": {"completionSignals": ["Customer exists"]},
            }
        )
        result = router.execute(bridge, self._context())
        self.assertEqual(result.traces[0].outputs["value"]["id"], 7)
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "POST"])


if __name__ == "__main__":
    unittest.main()
