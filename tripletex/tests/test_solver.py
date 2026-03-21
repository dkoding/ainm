from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.client import TripletexAPIError
from app.models import SolveRequest, TripletexCredentials
from app.openapi_registry import ResourceCapability
from app.planner import PlannerError
from app.solver import SolveError, TaskInputError, TaskPreconditionError, TripletexSolver
from app.tasking import TaskAnalysis


class _FakePlanner:
    def __init__(self, analysis: TaskAnalysis) -> None:
        self.analysis = analysis
        self.analyze_calls = 0
        self.next_step_calls = 0

    def analyze_task(self, *, task_prompt: str, attachments: list[object]) -> TaskAnalysis:
        self.analyze_calls += 1
        return self.analysis

    def next_step(self, **_: object) -> object:
        self.next_step_calls += 1
        raise AssertionError("planner.next_step should not be called when LLM step planning is disabled")


class _FakeExecutor:
    def __init__(self, client: object, registry: object) -> None:
        self.client = client
        self.registry = registry

    def validate(self, command: object) -> None:
        return None

    def execute_prevalidated(self, command: object) -> dict[str, object]:
        raise AssertionError("No Tripletex API call should be attempted in this test")


class _FakeRegistry:
    def match_operation(self, *, method: str, path: str) -> object | None:
        return None

    def resource_capability(self, resource_family: str | None) -> ResourceCapability:
        return ResourceCapability(
            resource_family=resource_family or "other",
            primary_prefix=None,
            collection_path=None,
            detail_path=None,
            create_path=None,
            update_path=None,
            delete_path=None,
            reverse_paths=(),
            supported_methods=(),
            search_parameters=(),
            required_path_parameters=(),
            request_body_summaries=(),
        )


class _ForbiddenExecutor:
    def __init__(self, client: object, registry: object) -> None:
        self.client = client
        self.registry = registry

    def validate(self, command: object) -> None:
        return None

    def execute_prevalidated(self, command: object) -> dict[str, object]:
        method = getattr(command, "method", "GET")
        path = getattr(command, "path", "/department")
        raise TripletexAPIError(
            403,
            method,
            path,
            {
                "error": (
                    "Invalid or expired proxy token. Each submission receives a unique token - "
                    "do not reuse tokens from previous submissions."
                ),
                "source": "nmiai-proxy",
            },
        )


class _StopAfterFirstExecuteExecutor:
    def __init__(self, client: object, registry: object) -> None:
        self.client = client
        self.registry = registry

    def validate(self, command: object) -> None:
        return None

    def execute_prevalidated(self, command: object) -> dict[str, object]:
        method = getattr(command, "method", "GET")
        path = getattr(command, "path", "/")
        raise RuntimeError(f"executed {method} {path}")


class SolverArchitectureTests(unittest.TestCase):
    def test_solver_does_not_fallback_to_llm_step_planning_by_default(self) -> None:
        analysis = TaskAnalysis(
            objective="Inspect bank data",
            task_family="bank.search",
            operation="other",
            target_resource="bank",
            method_name="RunBankOpenAPIWorkflow",
            method_arguments={},
            missing_required_arguments=[],
        )
        fake_planner = _FakePlanner(analysis)
        request = SolveRequest(
            prompt="Inspect bank data",
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url="https://example.invalid",
                session_token="token",
            ),
        )

        with patch.dict(
            os.environ,
            {"TRIPLETEX_ENABLE_LLM_STEP_PLANNING": "false", "TRIPLETEX_API_KEY": ""},
            clear=False,
        ):
            with patch("app.solver.build_planner", return_value=fake_planner):
                with patch("app.solver.TripletexOpenAPIRegistry.from_default_spec", return_value=_FakeRegistry()):
                    with patch("app.solver.GeneratedAPIMethodRegistry.from_default_spec", return_value=object()):
                        with patch("app.solver.TripletexCommandExecutor", _FakeExecutor):
                            solver = TripletexSolver()
                            with self.assertRaises(TaskPreconditionError) as exc_info:
                                solver.solve(request, authorization_header=None)

        self.assertIn("Unable to continue the deterministic workflow", str(exc_info.exception))
        self.assertEqual(fake_planner.analyze_calls, 1)
        self.assertEqual(fake_planner.next_step_calls, 0)

    def test_solver_turns_deterministic_auth_failures_into_precondition_errors(self) -> None:
        analysis = TaskAnalysis(
            objective="Create employee from contract",
            task_family="employee.create",
            operation="create",
            target_resource="employee",
            method_name="RunEmployeeOnboardingWorkflow",
            method_arguments={
                "firstName": "Miguel",
                "lastName": "Costa",
                "email": "miguel.costa@example.org",
                "departmentName": "Innkjop",
            },
            missing_required_arguments=[],
        )
        fake_planner = _FakePlanner(analysis)
        request = SolveRequest(
            prompt="Create employee from contract",
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url="https://example.invalid",
                session_token="token",
            ),
        )

        with patch.dict(
            os.environ,
            {"TRIPLETEX_ENABLE_LLM_STEP_PLANNING": "false", "TRIPLETEX_API_KEY": ""},
            clear=False,
        ):
            with patch("app.solver.build_planner", return_value=fake_planner):
                with patch("app.solver.TripletexOpenAPIRegistry.from_default_spec", return_value=_FakeRegistry()):
                    with patch("app.solver.GeneratedAPIMethodRegistry.from_default_spec", return_value=object()):
                        with patch("app.solver.TripletexCommandExecutor", _ForbiddenExecutor):
                            solver = TripletexSolver()
                            with self.assertRaises(TaskPreconditionError) as exc_info:
                                solver.solve(request, authorization_header=None)

        self.assertIn("missing or invalid access", str(exc_info.exception))
        self.assertIn("Invalid or expired proxy token", str(exc_info.exception))
        self.assertEqual(fake_planner.analyze_calls, 1)
        self.assertEqual(fake_planner.next_step_calls, 0)

    def test_solver_uses_planner_analysis_for_travel_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Create travel expense",
            task_family="travelexpense.create",
            operation="create",
            target_resource="travelExpense",
            method_name="RunTravelExpenseWorkflow",
            method_arguments={
                "title": "Kundenbesuch Trondheim",
                "employeeEmail": "elias.hoffmann@example.org",
                "perDiemRate": 800,
                "expenses": [
                    {"description": "Flight ticket", "amount": 6300},
                    {"description": "Taxi", "amount": 250},
                ],
            },
            missing_required_arguments=["departureDate", "returnDate"],
        )
        fake_planner = _FakePlanner(analysis)
        request = SolveRequest(
            prompt=(
                'Erfassen Sie eine Reisekostenabrechnung für Elias Hoffmann '
                '(elias.hoffmann@example.org) für "Kundenbesuch Trondheim". '
                "Die Reise dauerte 5 Tage mit Tagegeld (Tagessatz 800 NOK). "
                "Auslagen: Flugticket 6300 NOK und Taxi 250 NOK."
            ),
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url="https://example.invalid",
                session_token="token",
            ),
        )

        with patch.dict(
            os.environ,
            {"TRIPLETEX_ENABLE_LLM_STEP_PLANNING": "false", "TRIPLETEX_API_KEY": ""},
            clear=False,
        ):
            with patch("app.solver.build_planner", return_value=fake_planner):
                with patch("app.solver.TripletexOpenAPIRegistry.from_default_spec", return_value=_FakeRegistry()):
                    with patch("app.solver.GeneratedAPIMethodRegistry.from_default_spec", return_value=object()):
                        with patch("app.solver.TripletexCommandExecutor", _FakeExecutor):
                            solver = TripletexSolver()
                            with self.assertRaises(TaskInputError) as exc_info:
                                solver.solve(request, authorization_header=None)

        self.assertIn("RunTravelExpenseWorkflow", str(exc_info.exception))
        self.assertIn("departureDate", str(exc_info.exception))
        self.assertIn("returnDate", str(exc_info.exception))
        self.assertEqual(fake_planner.analyze_calls, 1)

    def test_solver_uses_planner_analysis_for_month_end_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Perform month-end closing",
            task_family="ledger.month_end",
            operation="create",
            target_resource="ledger",
            method_name="RunMonthEndClosingWorkflow",
            method_arguments={
                "voucherDate": "2026-03-31",
                "periodizationAmount": 9750,
                "prepaidAccountNumber": "1710",
                "depreciationAmount": 2665.28,
                "depreciationExpenseAccountNumber": "6030",
                "payrollExpenseAccountNumber": "5000",
                "payrollLiabilityAccountNumber": "2900",
            },
            missing_required_arguments=["periodizationExpenseAccountNumber", "depreciationAccumulatedAccountNumber", "payrollAccrualAmount"],
        )
        fake_planner = _FakePlanner(analysis)
        request = SolveRequest(
            prompt=(
                "Gjer månavslutninga for mars 2026. Periodiser forskotsbetalt kostnad "
                "(9750 kr per månad frå konto 1710 til kostnadskonto). "
                "Bokfør månadleg avskriving for eit driftsmiddel med innkjøpskost 191900 kr "
                "og levetid 6 år (lineær avskriving til konto 6030). "
                "Kontroller at saldobalansen går i null. "
                "Bokfør også ei lønnsavsetjing (debet lønnskostnad konto 5000, kredit påløpt lønn konto 2900)."
            ),
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url="https://example.invalid",
                session_token="token",
            ),
        )

        with patch.dict(
            os.environ,
            {"TRIPLETEX_ENABLE_LLM_STEP_PLANNING": "false", "TRIPLETEX_API_KEY": ""},
            clear=False,
        ):
            with patch("app.solver.build_planner", return_value=fake_planner):
                with patch("app.solver.TripletexOpenAPIRegistry.from_default_spec", return_value=_FakeRegistry()):
                    with patch("app.solver.GeneratedAPIMethodRegistry.from_default_spec", return_value=object()):
                        with patch("app.solver.TripletexCommandExecutor", _FakeExecutor):
                            solver = TripletexSolver()
                            with self.assertRaises(TaskInputError) as exc_info:
                                solver.solve(request, authorization_header=None)

        self.assertIn("RunMonthEndClosingWorkflow", str(exc_info.exception))
        self.assertIn("payrollAccrualAmount", str(exc_info.exception))
        self.assertIn("depreciationAccumulatedAccountNumber", str(exc_info.exception))
        self.assertEqual(fake_planner.analyze_calls, 1)

    def test_solver_runs_deterministic_salary_payroll_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Run payroll for Jules Leroy",
            task_family="salary.create",
            operation="create",
            target_resource="salary",
            method_name="RunSalaryPayrollWorkflow",
            method_arguments={
                "employeeEmail": "jules.leroy@example.org",
                "date": "2026-03-31",
                "month": 3,
                "year": 2026,
                "salaryLines": [
                    {"salaryTypeName": "Fastlønn", "amount": 56950},
                    {"salaryTypeName": "Bonus", "amount": 9350},
                ],
            },
            missing_required_arguments=[],
        )
        fake_planner = _FakePlanner(analysis)
        request = SolveRequest(
            prompt="Exécutez la paie de Jules Leroy pour ce mois.",
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url="https://example.invalid",
                session_token="token",
            ),
        )

        with patch.dict(
            os.environ,
            {"TRIPLETEX_ENABLE_LLM_STEP_PLANNING": "false", "TRIPLETEX_API_KEY": ""},
            clear=False,
        ):
            with patch("app.solver.build_planner", return_value=fake_planner):
                with patch("app.solver.GeneratedAPIMethodRegistry.from_default_spec", return_value=object()):
                    with patch("app.solver.TripletexCommandExecutor", _StopAfterFirstExecuteExecutor):
                        solver = TripletexSolver()
                        with self.assertRaises(RuntimeError) as exc_info:
                            solver.solve(request, authorization_header=None)

        self.assertIn("executed GET /employee", str(exc_info.exception))
        self.assertEqual(fake_planner.analyze_calls, 1)

    def test_solver_runs_deterministic_bank_reconciliation_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Reconcile bank statement",
            task_family="bank.reconcile",
            operation="other",
            target_resource="bank",
            method_name="RunBankReconciliationWorkflow",
            method_arguments={
                "statementEntries": [
                    {
                        "entryId": "line-1",
                        "paymentDate": "2026-03-21",
                        "direction": "incoming",
                        "amount": 17724,
                        "invoiceNumber": "2026-1042",
                        "customer": {
                            "customerName": "Havbris AS",
                            "organizationNumber": "887674973",
                        },
                    }
                ]
            },
            missing_required_arguments=[],
        )
        fake_planner = _FakePlanner(analysis)
        request = SolveRequest(
            prompt="Reconcile the attached bank statement against invoices.",
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url="https://example.invalid",
                session_token="token",
            ),
        )

        with patch.dict(
            os.environ,
            {"TRIPLETEX_ENABLE_LLM_STEP_PLANNING": "false", "TRIPLETEX_API_KEY": ""},
            clear=False,
        ):
            with patch("app.solver.build_planner", return_value=fake_planner):
                with patch("app.solver.GeneratedAPIMethodRegistry.from_default_spec", return_value=object()):
                    with patch("app.solver.TripletexCommandExecutor", _StopAfterFirstExecuteExecutor):
                        solver = TripletexSolver()
                        with self.assertRaises(RuntimeError) as exc_info:
                            solver.solve(request, authorization_header=None)

        self.assertIn("executed GET /customer", str(exc_info.exception))
        self.assertEqual(fake_planner.analyze_calls, 1)

    def test_solver_enforces_internal_solve_budget(self) -> None:
        analysis = TaskAnalysis(
            objective="Inspect bank data",
            task_family="bank.search",
            operation="other",
            target_resource="bank",
            method_name="RunBankOpenAPIWorkflow",
            method_arguments={},
            missing_required_arguments=[],
        )
        fake_planner = _FakePlanner(analysis)
        request = SolveRequest(
            prompt="Inspect bank data",
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url="https://example.invalid",
                session_token="token",
            ),
        )

        with patch.dict(
            os.environ,
            {
                "TRIPLETEX_ENABLE_LLM_STEP_PLANNING": "false",
                "TRIPLETEX_API_KEY": "",
                "TRIPLETEX_SOLVE_BUDGET_SECONDS": "0",
            },
            clear=False,
        ):
            with patch("app.solver.build_planner", return_value=fake_planner):
                with patch("app.solver.TripletexOpenAPIRegistry.from_default_spec", return_value=_FakeRegistry()):
                    with patch("app.solver.GeneratedAPIMethodRegistry.from_default_spec", return_value=object()):
                        with patch("app.solver.TripletexCommandExecutor", _FakeExecutor):
                            solver = TripletexSolver()
                            with self.assertRaises(SolveError) as exc_info:
                                solver.solve(request, authorization_header=None)

        self.assertIn("solve budget", str(exc_info.exception).lower())
        self.assertEqual(fake_planner.analyze_calls, 1)

    def test_solver_rejects_wrapper_analysis_when_structured_contract_requires_curated_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Create internal projects from ledger deltas",
            task_family="project.create",
            operation="other",
            target_resource="project",
            method_name="RunProjectOpenAPIWorkflow",
            method_arguments={},
            missing_required_arguments=[],
            search_hints={"date_from": "2026-01-01", "date_to": "2026-02-29"},
            payload_fields={"isInternal": True},
        )
        fake_planner = _FakePlanner(analysis)
        request = SolveRequest(
            prompt="Analyze ledger deltas and create internal projects",
            files=[],
            tripletex_credentials=TripletexCredentials(
                base_url="https://example.invalid",
                session_token="token",
            ),
        )

        with patch.dict(
            os.environ,
            {"TRIPLETEX_ENABLE_LLM_STEP_PLANNING": "false", "TRIPLETEX_API_KEY": ""},
            clear=False,
        ):
            with patch("app.solver.build_planner", return_value=fake_planner):
                with patch("app.solver.TripletexOpenAPIRegistry.from_default_spec", return_value=_FakeRegistry()):
                    with patch("app.solver.GeneratedAPIMethodRegistry.from_default_spec", return_value=object()):
                        with patch("app.solver.TripletexCommandExecutor", _StopAfterFirstExecuteExecutor):
                            solver = TripletexSolver()
                            with self.assertRaises(PlannerError) as exc_info:
                                solver.solve(request, authorization_header=None)

        self.assertIn("Planner contract violation", str(exc_info.exception))
        self.assertIn("RunExpenseIncreaseProjectWorkflow", str(exc_info.exception))
        self.assertEqual(fake_planner.analyze_calls, 1)


if __name__ == "__main__":
    unittest.main()
