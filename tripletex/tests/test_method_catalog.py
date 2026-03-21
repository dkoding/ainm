from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.internal_tasks import (
    METHOD_SPECS,
    _openapi_workflow_method_name,
    derive_internal_task,
    documented_task_category_coverage,
    method_coverage_snapshot,
    normalize_task_analysis_method_selection,
    planner_method_hints,
    validate_task_analysis_contract,
    workflow_prefixes_for_method,
)
from app.openapi_registry import workflow_resource_families
from app.tasking import TaskAnalysis
from app.workflow_router import DeterministicWorkflowRouter


class MethodCatalogTests(unittest.TestCase):
    def test_openapi_resource_families_have_named_workflow_methods(self) -> None:
        for resource_family, _label in workflow_resource_families():
            method_name = _openapi_workflow_method_name(resource_family)
            spec = METHOD_SPECS.get(method_name)
            self.assertIsNotNone(spec, resource_family)
            assert spec is not None
            self.assertEqual(spec.execution_strategy, "openapi_wrapper")
            self.assertEqual(spec.target_resource, resource_family)

    def test_planner_hints_expose_only_concrete_methods(self) -> None:
        hints = planner_method_hints()
        forbidden_method = "Unknown" + "Method"

        self.assertTrue(hints)
        self.assertNotIn(forbidden_method, {hint["method_name"] for hint in hints})
        self.assertIn("curated_router", {hint["execution_strategy"] for hint in hints})
        self.assertIn("openapi_wrapper", {hint["execution_strategy"] for hint in hints})
        self.assertTrue(all("coverage_status" in hint for hint in hints))
        self.assertTrue(all("planner_choose_when" in hint for hint in hints))
        self.assertTrue(all("planner_avoid_when" in hint for hint in hints))

    def test_documented_categories_have_coded_workflow_mappings(self) -> None:
        coverage = documented_task_category_coverage()

        self.assertTrue(all(coverage.values()), coverage)

    def test_coverage_snapshot_includes_wrapper_only_methods(self) -> None:
        snapshot = method_coverage_snapshot()

        self.assertTrue(any(item["coverage_status"] == "wrapper_only" for item in snapshot))
        self.assertTrue(any(item["coverage_status"] == "coded" for item in snapshot))

    def test_supplier_create_contract_rejects_customer_method(self) -> None:
        analysis = TaskAnalysis(
            objective="Register supplier data",
            task_family="supplier.create",
            operation="create",
            target_resource="supplier",
            method_name="CreateCustomer",
            method_arguments={},
            search_hints={"organizationNumber": "947820605"},
            payload_fields={"supplierName": "Polaris AS", "supplierOrganizationNumber": "947820605"},
        )

        with self.assertRaises(ValueError) as exc_info:
            validate_task_analysis_contract(analysis)
        self.assertIn("expected_method_name='CreateSupplier'", str(exc_info.exception))

    def test_supplier_invoice_contract_requires_specialized_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Register supplier invoice from Polaris AS",
            task_family="supplierinvoice.create",
            operation="create",
            target_resource="supplierinvoice",
            method_name="RunSupplierOpenAPIWorkflow",
            method_arguments={},
            payload_fields={
                "supplierName": "Polaris AS",
                "supplierOrganizationNumber": "947820605",
                "invoiceNumber": "SUP-1001",
                "description": "Consulting services",
                "amountIncludingVat": "84450",
            },
        )

        with self.assertRaises(ValueError) as exc_info:
            validate_task_analysis_contract(analysis)
        self.assertIn("expected_method_name='RegisterSupplierInvoice'", str(exc_info.exception))

    def test_simple_customer_method_stays_valid(self) -> None:
        analysis = TaskAnalysis(
            objective="Create customer Tindra AS",
            task_family="customer.create",
            operation="create",
            target_resource="customer",
            method_name="CreateCustomer",
            method_arguments={},
            payload_fields={"name": "Tindra AS", "organizationNumber": "925122025"},
        )

        validate_task_analysis_contract(analysis)
        normalized = normalize_task_analysis_method_selection(task_analysis=analysis)
        self.assertEqual(normalized.method_name, "CreateCustomer")

    def test_travel_expense_wrapper_contract_requires_curated_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Create travel expense for Elias Hoffmann",
            task_family="travelexpense.create",
            operation="create",
            target_resource="travelExpense",
            method_name="RunTravelExpenseOpenAPIWorkflow",
            method_arguments={},
            search_hints={"employeeEmail": "elias.hoffmann@example.org"},
            payload_fields={"title": "Kundenbesuch Trondheim", "departureDate": "2026-03-01", "returnDate": "2026-03-05"},
        )

        with self.assertRaises(ValueError) as exc_info:
            validate_task_analysis_contract(analysis)
        self.assertIn("expected_method_name='RunTravelExpenseWorkflow'", str(exc_info.exception))

    def test_month_end_wrapper_contract_requires_curated_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Perform month-end closing",
            task_family="ledger.other",
            operation="other",
            target_resource="ledger",
            method_name="RunLedgerOpenAPIWorkflow",
            method_arguments={},
            payload_fields={
                "voucherDate": "2026-03-31",
                "prepaidAccountNumber": "1710",
                "periodizationExpenseAccountNumber": "6500",
                "periodizationAmount": 9750,
                "depreciationAmount": 2665.28,
                "depreciationExpenseAccountNumber": "6030",
                "depreciationAccumulatedAccountNumber": "1290",
                "payrollAccrualAmount": 50000,
                "payrollExpenseAccountNumber": "5000",
                "payrollLiabilityAccountNumber": "2900",
            },
        )

        with self.assertRaises(ValueError) as exc_info:
            validate_task_analysis_contract(analysis)
        self.assertIn("expected_method_name='RunMonthEndClosingWorkflow'", str(exc_info.exception))

    def test_project_wrapper_contract_requires_expense_increase_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Create internal projects from rising expense accounts",
            task_family="project.create",
            operation="other",
            target_resource="project",
            method_name="RunProjectOpenAPIWorkflow",
            method_arguments={
                "baselineDateFrom": "2026-01-01",
                "baselineDateTo": "2026-01-31",
                "comparisonDateFrom": "2026-02-01",
                "comparisonDateTo": "2026-02-28",
                "topCount": 3,
                "isInternal": True,
                "createActivity": True,
            },
            search_hints={
                "date_from": "2026-01-01",
                "date_to": "2026-02-28",
            },
            payload_fields={"isInternal": True, "createActivity": True},
        )

        with self.assertRaises(ValueError) as exc_info:
            validate_task_analysis_contract(analysis)
        self.assertIn("expected_method_name='RunExpenseIncreaseProjectWorkflow'", str(exc_info.exception))

    def test_salary_wrapper_contract_requires_curated_payroll_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Run payroll for Jules Leroy",
            task_family="salary.create",
            operation="create",
            target_resource="salary",
            method_name="RunSalaryOpenAPIWorkflow",
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
            search_hints={"employeeEmail": "jules.leroy@example.org"},
            payload_fields={"date": "2026-03-31", "month": 3, "year": 2026},
        )

        with self.assertRaises(ValueError) as exc_info:
            validate_task_analysis_contract(analysis)
        self.assertIn("expected_method_name='RunSalaryPayrollWorkflow'", str(exc_info.exception))

    def test_bank_wrapper_contract_requires_curated_reconciliation_workflow(self) -> None:
        analysis = TaskAnalysis(
            objective="Reconcile bank statement against invoices",
            task_family="bank.reconcile",
            operation="other",
            target_resource="bank",
            method_name="RunBankOpenAPIWorkflow",
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
            payload_fields={"statementEntries": [{"entryId": "line-1"}]},
        )

        with self.assertRaises(ValueError) as exc_info:
            validate_task_analysis_contract(analysis)
        self.assertIn("expected_method_name='RunBankReconciliationWorkflow'", str(exc_info.exception))

    def test_generic_openapi_wrapper_is_rejected_for_specific_resource(self) -> None:
        analysis = TaskAnalysis(
            objective="Inspect bank transactions",
            task_family="bank.search",
            operation="search",
            target_resource="bank",
            method_name="RunGenericOpenAPIWorkflow",
            method_arguments={},
            search_hints={"dateFrom": "2026-01-01", "dateTo": "2026-01-31"},
        )

        with self.assertRaises(ValueError) as exc_info:
            validate_task_analysis_contract(analysis)
        self.assertIn("expected_method_name='RunBankOpenAPIWorkflow'", str(exc_info.exception))

    def test_company_wrapper_stays_valid_for_department_module_enablement(self) -> None:
        analysis = TaskAnalysis(
            objective="Enable department accounting",
            task_family="department.enable_module",
            operation="update",
            target_resource="company",
            method_name="RunCompanyOpenAPIWorkflow",
            method_arguments={"moduleDepartmentAccounting": True},
            payload_fields={"moduleDepartmentAccounting": True},
        )

        validate_task_analysis_contract(analysis)
        normalized = normalize_task_analysis_method_selection(
            task_prompt="Delete the invoice for Example Corp immediately",
            task_analysis=analysis,
        )

        self.assertEqual(normalized.method_name, "RunCompanyOpenAPIWorkflow")
        self.assertEqual(normalized.method_arguments["moduleDepartmentAccounting"], True)

    def test_method_normalization_only_canonicalizes_names(self) -> None:
        analysis = TaskAnalysis(
            objective="Create travel expense for Elias Hoffmann",
            task_family="travelexpense.create",
            operation="create",
            target_resource="travelExpense",
            method_name="runtravelexpenseworkflow",
            method_arguments={"title": "Kundenbesuch Trondheim"},
            search_hints={"employeeEmail": "elias.hoffmann@example.org"},
        )

        normalized = normalize_task_analysis_method_selection(
            task_prompt="Delete the invoice for Example Corp immediately",
            task_analysis=analysis,
        )

        self.assertEqual(normalized.method_name, "RunTravelExpenseWorkflow")
        self.assertEqual(normalized.method_arguments, {"title": "Kundenbesuch Trondheim"})
        self.assertEqual(normalized.search_hints, {"employeeEmail": "elias.hoffmann@example.org"})

    def test_project_lifecycle_workflow_prefixes_are_cross_resource(self) -> None:
        prefixes = workflow_prefixes_for_method("RunProjectLifecycleWorkflow")

        self.assertIn("/customer", prefixes)
        self.assertIn("/project", prefixes)
        self.assertIn("/employee", prefixes)
        self.assertIn("/activity", prefixes)
        self.assertIn("/timesheet", prefixes)
        self.assertIn("/supplier", prefixes)
        self.assertIn("/incomingInvoice", prefixes)
        self.assertIn("/order", prefixes)
        self.assertIn("/invoice", prefixes)
        self.assertIn("/ledger", prefixes)

    def test_employee_upsert_uses_richer_employee_workflow_when_employment_fields_exist(self) -> None:
        analysis = TaskAnalysis(
            objective="Create or update employee with employment details",
            task_family="employee.update",
            operation="update",
            target_resource="employee",
            method_name="UpsertEmployee",
            method_arguments={},
            search_hints={
                "email": "olav.johansen@example.org",
                "firstName": "Olav",
                "lastName": "Johansen",
            },
            payload_fields={
                "firstName": "Olav",
                "lastName": "Johansen",
                "email": "olav.johansen@example.org",
                "departmentName": "Produksjon",
                "startDate": "2026-04-01",
                "employmentForm": "Fast stilling",
                "remunerationType": "Fastlønn (månedlig)",
            },
        )
        task = derive_internal_task(task_analysis=analysis)
        router = DeterministicWorkflowRouter()

        decision = router.next_step(
            internal_task=task,
            task_analysis=analysis,
            history=[],
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "GET")
        self.assertEqual(decision.action.path, "/department")
        self.assertEqual(decision.action.params, {"name": "Produksjon"})


if __name__ == "__main__":
    unittest.main()
