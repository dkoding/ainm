from __future__ import annotations

import unittest

from app.benchmark import BenchmarkAnalysis, NormalizedRequest, normalize_text, tokenize_text
from app.contracts import LLMBridgeDocument, SolveRequest
from app.contracts.execution import ExecutionResult
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
        self.plan_calls = 0

    def plan(self, request: SolveRequest, *, current_date: str, timezone: str, request_id: str) -> LLMBridgeDocument:
        self.plan_calls += 1
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
    def __init__(self, errors: list[RawExecutionError], *, result: ExecutionResult | None = None) -> None:
        self.errors = list(errors)
        self.result = result or ExecutionResult()
        self.executed_bridges: list[LLMBridgeDocument] = []

    def _selected_policy_keys(self, bridge: LLMBridgeDocument) -> list[str]:
        return []

    def execute(self, bridge: LLMBridgeDocument, context: object) -> object:
        self.executed_bridges.append(bridge)
        if self.errors:
            raise self.errors.pop(0)
        return self.result


class StubBenchmarkRuntime:
    def __init__(self, bridge: LLMBridgeDocument | None) -> None:
        self.bridge = bridge

    def prepare_bridge(
        self,
        request: SolveRequest,
        *,
        current_date: str,
        timezone: str,
        request_id: str,
    ) -> tuple[BenchmarkAnalysis, LLMBridgeDocument | None]:
        normalized_request = NormalizedRequest(
            prompt=request.prompt,
            prompt_normalized=normalize_text(request.prompt),
            prompt_tokens=tokenize_text(request.prompt),
            attachments=(),
            attachment_media=(),
        )
        analysis = BenchmarkAnalysis(
            normalized_request=normalized_request,
            selected_family_id="employee.create_basic" if self.bridge else None,
            selected_route_kind="flow" if self.bridge else None,
            selected_route_name="employee.create_basic" if self.bridge else None,
            selected_flow_name="employee.create_basic" if self.bridge else None,
            selected_executor_name="employee.create_basic" if self.bridge else None,
            supported_by_executor=bool(self.bridge),
            execution_mode="benchmark_bridge" if self.bridge else "legacy_fallback",
            candidates=(),
            notes=("stub_benchmark_runtime",),
        )
        return analysis, self.bridge


class SolveServiceTests(unittest.TestCase):
    def test_restricted_api_403_is_demoted_to_blocked_issue(self) -> None:
        restricted_error = RawExecutionError(
            message="Tripletex returned HTTP 403 for GET /incomingInvoice/321.",
            status_code=403,
            details={
                "operationId": "IncomingInvoice_get",
                "body": {
                    "status": 403,
                    "code": 9000,
                    "message": "You do not have permission to access this feature.",
                },
            },
        )
        service = SolveService(planner=StubPlanner(_bridge()), router=StubRouter([restricted_error]))
        request = SolveRequest.model_validate(
            {
                "prompt": "Bookkeep the attached supplier invoice",
                "files": [],
                "tripletex_credentials": {
                    "base_url": "https://example.test/v2",
                    "session_token": "token",
                },
            }
        )
        planner = StubPlanner(_bridge())

        with self.assertRaises(RawExecutionError) as ctx:
            SolveService(
                planner=planner,
                router=StubRouter([restricted_error]),
                benchmark_runtime=StubBenchmarkRuntime(None),
            ).execute(request)

        self.assertEqual(ctx.exception.message, "Bridge JSON is blocked.")
        self.assertIn("pilot-enabled tenants", ctx.exception.details["blockingIssues"][0])
        self.assertEqual(planner.plan_calls, 1)

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
        planner = StubPlanner(_bridge())

        with self.assertRaises(RawExecutionError) as ctx:
            SolveService(
                planner=planner,
                router=StubRouter([initial_error, retry_error]),
                benchmark_runtime=StubBenchmarkRuntime(None),
            ).execute(request)

        self.assertEqual(ctx.exception.message, "Bridge JSON is blocked.")
        self.assertEqual(
            ctx.exception.details["blockingIssues"],
            ["Tripletex requires department.id: Feltet må fylles ut."],
        )
        self.assertEqual(planner.plan_calls, 1)

    def test_benchmark_bridge_runs_before_legacy_planner(self) -> None:
        planner = StubPlanner(_bridge())
        router = StubRouter([])
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

        service = SolveService(
            planner=planner,
            router=router,
            benchmark_runtime=StubBenchmarkRuntime(_bridge()),
        )

        result = service.execute(request)

        self.assertEqual(planner.plan_calls, 0)
        self.assertEqual(len(router.executed_bridges), 1)
        self.assertIsInstance(result, ExecutionResult)


if __name__ == "__main__":
    unittest.main()
