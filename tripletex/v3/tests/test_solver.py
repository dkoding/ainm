from __future__ import annotations

import unittest

from app.contracts import LLMBridgeDocument, SolveRequest
from app.raw.errors import RawExecutionError
from app.solver import SolveService


def _bridge() -> LLMBridgeDocument:
    return LLMBridgeDocument.model_validate(
        {
            "contractVersion": "tripletex.llm_bridge.v1",
            "language": {"promptOriginal": "create employee", "promptCanonical": "create employee"},
            "understanding": {"objective": "create employee"},
            "executionPlan": {
                "selectedFlows": [
                    {
                        "stepId": "flow_1",
                        "flowName": "employee.create_basic",
                        "flowType": "business_flow",
                        "inputs": {"first_name": "Jane", "last_name": "Doe"},
                    }
                ]
            },
            "validation": {"isExecutable": True, "blockingIssues": [], "warnings": []},
            "completion": {"completionSignals": ["Employee created"]},
        }
    )


class StubPlanner:
    def __init__(self, bridge: LLMBridgeDocument) -> None:
        self.bridge = bridge

    def plan(self, request: SolveRequest, *, current_date: str, timezone: str, request_id: str) -> LLMBridgeDocument:
        return self.bridge

    def repair_after_execution_error(
        self,
        *,
        request: SolveRequest,
        bridge: LLMBridgeDocument,
        error: RawExecutionError,
        current_date: str,
        timezone: str,
        request_id: str,
    ) -> LLMBridgeDocument:
        return self.bridge


class StubRouter:
    def __init__(self, errors: list[RawExecutionError]) -> None:
        self.errors = list(errors)

    def _selected_policy_keys(self, bridge: LLMBridgeDocument) -> list[str]:
        return []

    def execute(self, bridge: LLMBridgeDocument, context: object) -> object:
        raise self.errors.pop(0)


class SolveServiceTests(unittest.TestCase):
    def test_second_live_missing_field_error_is_demoted_to_blocked_issue(self) -> None:
        initial_error = RawExecutionError(
            message="Tripletex returned HTTP 422 for POST /employee.",
            status_code=422,
            details={
                "body": {
                    "validationMessages": [
                        {"field": None, "message": 'Brukertype kan ikke være "0" eller tom.'},
                    ]
                }
            },
        )
        retry_error = RawExecutionError(
            message="Tripletex returned HTTP 422 for POST /employee.",
            status_code=422,
            details={
                "body": {
                    "validationMessages": [
                        {"field": "department.id", "message": "Feltet må fylles ut."},
                    ]
                }
            },
        )
        service = SolveService(planner=StubPlanner(_bridge()), router=StubRouter([initial_error, retry_error]))
        request = SolveRequest.model_validate(
            {
                "prompt": "Create employee Jane Doe",
                "files": [],
                "tripletex_credentials": {
                    "base_url": "https://example.test/v2",
                    "session_token": "token",
                },
            }
        )

        with self.assertRaises(RawExecutionError) as ctx:
            service.execute(request)

        self.assertEqual(ctx.exception.message, "Bridge JSON is blocked.")
        self.assertEqual(
            ctx.exception.details["blockingIssues"],
            ["Tripletex requires department.id: Feltet må fylles ut."],
        )


if __name__ == "__main__":
    unittest.main()
