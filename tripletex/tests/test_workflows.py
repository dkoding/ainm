from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.internal_tasks import derive_internal_task
from app.tasking import TaskAnalysis
from app.workflow_router import DeterministicWorkflowRouter


class WorkflowRoutingTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.router = DeterministicWorkflowRouter()

    def test_project_lifecycle_derivation_accepts_list_payloads(self) -> None:
        analysis = TaskAnalysis(
            objective="Execute the full project lifecycle",
            task_family="project.create_and_invoice",
            operation="other",
            target_resource="project",
            method_name="RunProjectLifecycleWorkflow",
            method_arguments={},
            search_hints={
                "projectName": "Dataplattform Tindra",
                "customerName": "Tindra AS",
                "customerOrganizationNumber": "925122025",
            },
            payload_fields={
                "projectName": "Dataplattform Tindra",
                "projectBudget": "432000",
                "customerName": "Tindra AS",
                "customerOrganizationNumber": "925122025",
                "timesheetEntries": [
                    {
                        "employeeName": "Astrid Hansen",
                        "employeeEmail": "astrid.hansen@example.org",
                        "hours": "42",
                    },
                    {
                        "employeeName": "Silje Berg",
                        "employeeEmail": "silje.berg@example.org",
                        "hours": "145",
                    },
                ],
            },
        )

        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)

        self.assertEqual(task.method_name, "RunProjectLifecycleWorkflow")
        self.assertEqual(task.flow_kind.value, "project.lifecycle.workflow")
        self.assertEqual(len(task.payload["timesheetEntries"]), 2)

    def test_project_lifecycle_posts_customer_after_empty_search(self) -> None:
        analysis = TaskAnalysis(
            objective="Execute the full project lifecycle",
            task_family="project.create_and_invoice",
            operation="other",
            target_resource="project",
            method_name="RunProjectLifecycleWorkflow",
            method_arguments={},
            search_hints={
                "projectName": "Dataplattform Tindra",
                "customerName": "Tindra AS",
                "customerOrganizationNumber": "925122025",
            },
            payload_fields={
                "projectName": "Dataplattform Tindra",
                "projectBudget": "432000",
                "customerName": "Tindra AS",
                "customerOrganizationNumber": "925122025",
            },
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/customer",
                    "params": {
                        "organizationNumber": "925122025",
                        "customerName": "Tindra AS",
                        "count": 10,
                    },
                },
                "response": {"values": []},
            }
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/customer")
        self.assertEqual(
            decision.action.json_body,
            {"name": "Tindra AS", "organizationNumber": "925122025"},
        )

    def test_supplier_upsert_posts_supplier_after_empty_search(self) -> None:
        analysis = TaskAnalysis(
            objective="Registrer leverandøren Fjelltopp AS",
            task_family="supplier.create",
            operation="create",
            target_resource="supplier",
            method_name="CreateSupplier",
            method_arguments={},
            payload_fields={
                "supplierName": "Fjelltopp AS",
                "supplierOrganizationNumber": "801180736",
            },
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/supplier",
                    "params": {
                        "organizationNumber": "801180736",
                        "count": 10,
                        "fields": "id,name,organizationNumber,email,invoiceEmail",
                    },
                },
                "response": {"values": []},
            }
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/supplier")
        self.assertEqual(
            decision.action.json_body,
            {"name": "Fjelltopp AS", "organizationNumber": "801180736"},
        )

    def test_supplier_invoice_adds_external_id_and_fails_fast_after_permission_error(self) -> None:
        analysis = TaskAnalysis(
            objective="Register supplier invoice from Riviere SARL",
            task_family="supplierinvoice.create",
            operation="create",
            target_resource="supplierinvoice",
            method_name="RegisterSupplierInvoice",
            method_arguments={},
            payload_fields={
                "supplierName": "Riviere SARL",
                "supplierOrganizationNumber": "838532624",
                "invoiceNumber": "INV-2026-2554",
                "invoiceDate": "2026-01-03",
                "dueDate": "2026-02-02",
                "description": "Programvarelisens",
                "accountNumber": "6340",
                "amountIncludingVat": "25000",
                "vatRate": "25",
            },
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/supplier",
                    "params": {
                        "organizationNumber": "838532624",
                        "count": 10,
                        "fields": "id,name,organizationNumber,email,invoiceEmail",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 108336201,
                            "name": "Riviere SARL",
                            "organizationNumber": "838532624",
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/ledger/account",
                    "params": {
                        "number": "6340",
                        "isApplicableForSupplierInvoice": True,
                        "count": 10,
                        "fields": "id,number,name,isApplicableForSupplierInvoice,vatLocked",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 359005448,
                            "number": 6340,
                            "name": "Lys, varme",
                            "isApplicableForSupplierInvoice": True,
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/ledger/vatType",
                    "params": {
                        "typeOfVat": "INCOMING_INVOICE",
                        "vatDate": "2026-01-03",
                        "count": 100,
                        "fields": "id,name,displayName,number,percentage",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 12,
                            "name": "Inngaaende 25%",
                            "displayName": "Inngaaende 25%",
                            "number": "12",
                            "percentage": 25.0,
                        }
                    ]
                },
            },
        ]

        first_decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(first_decision)
        assert first_decision is not None
        self.assertEqual(first_decision.kind, "action")
        self.assertEqual(first_decision.action.method, "POST")
        self.assertEqual(first_decision.action.path, "/incomingInvoice")
        self.assertEqual(
            first_decision.action.json_body["orderLines"][0]["externalId"],
            "INV-2026-2554",
        )

        history.append(
            {
                "request": {
                    "method": "POST",
                    "path": "/incomingInvoice",
                    "json": first_decision.action.json_body,
                },
                "error": {
                    "type": "tripletex_api",
                    "status_code": 403,
                    "message": "Tripletex API call failed: POST /incomingInvoice -> 403 [You do not have permission to access this feature.]",
                    "payload": {
                        "status": 403,
                        "code": 9000,
                        "message": "You do not have permission to access this feature.",
                    },
                },
            }
        )

        second_decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(second_decision)
        assert second_decision is not None
        self.assertEqual(second_decision.kind, "finish")
        self.assertIn("Unable to register the supplier invoice", second_decision.reason)
        self.assertIn("403", second_decision.reason)

    def test_salary_payroll_workflow_posts_salary_transaction(self) -> None:
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
                "generateTaxDeduction": True,
                "salaryLines": [
                    {"salaryTypeName": "Fastlønn", "amount": 56950},
                    {"salaryTypeName": "Bonus", "amount": 9350},
                ],
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/employee",
                    "params": {"email": "jules.leroy@example.org", "count": 10},
                },
                "response": {
                    "values": [
                        {
                            "id": 108380001,
                            "email": "jules.leroy@example.org",
                            "firstName": "Jules",
                            "lastName": "Leroy",
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/salary/type",
                    "params": {"name": "Fastlønn", "count": 20, "fields": "id,number,name,description"},
                },
                "response": {
                    "values": [
                        {"id": 501, "number": "100", "name": "Fastlønn", "description": "Base salary"}
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/salary/type",
                    "params": {"name": "Bonus", "count": 20, "fields": "id,number,name,description"},
                },
                "response": {
                    "values": [
                        {"id": 502, "number": "120", "name": "Bonus", "description": "Bonus"}
                    ]
                },
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/salary/transaction")
        self.assertEqual(decision.action.params, {"generateTaxDeduction": True})
        self.assertEqual(decision.action.json_body["date"], "2026-03-31")
        self.assertEqual(decision.action.json_body["month"], 3)
        self.assertEqual(decision.action.json_body["year"], 2026)
        self.assertEqual(decision.action.json_body["payslips"][0]["employee"], {"id": 108380001})
        self.assertEqual(
            decision.action.json_body["payslips"][0]["specifications"],
            [
                {"employee": {"id": 108380001}, "salaryType": {"id": 501}, "year": 2026, "month": 3, "amount": 56950.0},
                {"employee": {"id": 108380001}, "salaryType": {"id": 502}, "year": 2026, "month": 3, "amount": 9350.0},
            ],
        )

    def test_bank_reconciliation_registers_customer_invoice_payment(self) -> None:
        analysis = TaskAnalysis(
            objective="Reconcile customer payment",
            task_family="bank.reconcile",
            operation="other",
            target_resource="bank",
            method_name="RunBankReconciliationWorkflow",
            method_arguments={
                "fromDate": "2026-03-01",
                "toDate": "2026-03-31",
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
                ],
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/customer",
                    "params": {
                        "organizationNumber": "887674973",
                        "customerName": "Havbris AS",
                        "count": 10,
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 108293070,
                            "name": "Havbris AS",
                            "organizationNumber": "887674973",
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/invoice",
                    "params": {
                        "invoiceDateFrom": "2026-03-01",
                        "invoiceDateTo": "2026-03-31",
                        "invoiceNumber": "2026-1042",
                        "customerId": 108293070,
                        "count": 50,
                        "fields": "id,invoiceNumber,amount,amountCurrency,amountExcludingVat,amountExcludingVatCurrency,invoiceDate,invoiceComment,invoiceRemarks,customer(id),orderLines(description)",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 5001,
                            "invoiceNumber": "2026-1042",
                            "amount": 17724.0,
                            "customer": {"id": 108293070},
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/invoice/paymentType",
                    "params": {"count": 10},
                },
                "response": {"values": [{"id": 33, "description": "Bank payment"}]},
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "PUT")
        self.assertEqual(decision.action.path, "/invoice/5001/:payment")
        self.assertEqual(
            decision.action.params,
            {"paymentDate": "2026-03-21", "paymentTypeId": 33, "paidAmount": 17724.0},
        )

    def test_bank_reconciliation_registers_supplier_invoice_payment(self) -> None:
        analysis = TaskAnalysis(
            objective="Reconcile supplier payment",
            task_family="bank.reconcile",
            operation="other",
            target_resource="bank",
            method_name="RunBankReconciliationWorkflow",
            method_arguments={
                "fromDate": "2026-03-01",
                "toDate": "2026-03-31",
                "statementEntries": [
                    {
                        "entryId": "line-2",
                        "paymentDate": "2026-03-22",
                        "direction": "outgoing",
                        "amount": -14650,
                        "invoiceNumber": "SUP-2026-22",
                        "supplier": {
                            "supplierName": "Silveroak Ltd",
                            "organizationNumber": "973931156",
                        },
                    }
                ],
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/supplier",
                    "params": {
                        "organizationNumber": "973931156",
                        "supplierName": "Silveroak Ltd",
                        "count": 10,
                        "fields": "id,name,organizationNumber,email,invoiceEmail",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 108311500,
                            "name": "Silveroak Ltd",
                            "organizationNumber": "973931156",
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/incomingInvoice/search",
                    "params": {
                        "invoiceDateFrom": "2026-03-01",
                        "invoiceDateTo": "2026-03-31",
                        "invoiceNumber": "SUP-2026-22",
                        "vendorId": 108311500,
                        "count": 50,
                        "fields": "voucherId,invoiceNumber,invoiceAmount,amountCurrency,remainingAmount,vendor(id,name,organizationNumber)",
                    },
                },
                "response": {
                    "values": [
                        {
                            "voucherId": 9911,
                            "invoiceNumber": "SUP-2026-22",
                            "remainingAmount": 14650.0,
                            "vendor": {"id": 108311500},
                        }
                    ]
                },
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/incomingInvoice/9911/addPayment")
        self.assertEqual(
            decision.action.json_body,
            {
                "amountCurrency": 14650.0,
                "paymentDate": "2026-03-22",
                "partialPayment": False,
                "useDefaultPaymentType": True,
            },
        )

    def test_employee_onboarding_posts_employment_details_after_failed_occupation_lookup(self) -> None:
        analysis = TaskAnalysis(
            objective="Create employee from contract",
            task_family="employee.create",
            operation="create",
            target_resource="employee",
            method_name="RunEmployeeOnboardingWorkflow",
            method_arguments={},
            search_hints={
                "firstName": "Olav",
                "lastName": "Johansen",
                "email": "olav.johansen@example.org",
                "nationalIdentityNumber": "26078495390",
                "departmentName": "Produksjon",
            },
            payload_fields={
                "firstName": "Olav",
                "lastName": "Johansen",
                "email": "olav.johansen@example.org",
                "nationalIdentityNumber": "26078495390",
                "dateOfBirth": "1984-07-26",
                "departmentName": "Produksjon",
                "employmentForm": "Fast stilling",
                "remunerationType": "Fastlønn (månedlig)",
                "occupationCode": "3512",
                "percentageOfFullTimeEquivalent": "100",
                "annualSalary": "720000",
                "startDate": "2026-04-01",
            },
            attachment_required=True,
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {"method": "GET", "path": "/department", "params": {"name": "Produksjon"}},
                "response": {"values": []},
            },
            {
                "request": {"method": "POST", "path": "/department", "json": {"name": "Produksjon"}},
                "response": {"value": {"id": 10, "name": "Produksjon"}},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/employee",
                    "params": {
                        "email": "olav.johansen@example.org",
                        "firstName": "Olav",
                        "lastName": "Johansen",
                        "count": 10,
                    },
                },
                "response": {"values": []},
            },
            {
                "request": {
                    "method": "POST",
                    "path": "/employee",
                    "json": {
                        "firstName": "Olav",
                        "lastName": "Johansen",
                        "email": "olav.johansen@example.org",
                        "dateOfBirth": "1984-07-26",
                        "nationalIdentityNumber": "26078495390",
                        "department": {"id": 10},
                    },
                },
                "response": {
                    "value": {
                        "id": 20,
                        "firstName": "Olav",
                        "lastName": "Johansen",
                        "email": "olav.johansen@example.org",
                        "department": {"id": 10},
                    }
                },
            },
            {
                "request": {"method": "GET", "path": "/employee/20"},
                "response": {
                    "value": {
                        "id": 20,
                        "version": 1,
                        "firstName": "Olav",
                        "lastName": "Johansen",
                        "email": "olav.johansen@example.org",
                        "department": {"id": 10},
                        "dateOfBirth": "1984-07-26",
                        "nationalIdentityNumber": "26078495390",
                    }
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/employee/employment",
                    "params": {
                        "employeeId": 20,
                        "count": 20,
                        "fields": "id,version,startDate,endDate,employee(id),employmentDetails",
                    },
                },
                "response": {"values": []},
            },
            {
                "request": {
                    "method": "POST",
                    "path": "/employee/employment",
                    "json": {"employee": {"id": 20}, "startDate": "2026-04-01"},
                },
                "response": {"value": {"id": 30, "employee": {"id": 20}, "startDate": "2026-04-01"}},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/employee/employment/occupationCode",
                    "params": {"code": "3512", "count": 20, "fields": "id,nameNO,code"},
                },
                "response": {"values": []},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/employee/employment/details",
                    "params": {
                        "employmentId": "30",
                        "count": 20,
                        "fields": "id,version,date,employment(id),employmentForm,remunerationType,occupationCode,percentageOfFullTimeEquivalent,annualSalary,hourlyWage",
                    },
                },
                "response": {"values": []},
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/employee/employment/details")
        self.assertEqual(
            decision.action.json_body,
            {
                "employment": {"id": 30},
                "date": "2026-04-01",
                "employmentForm": "PERMANENT",
                "remunerationType": "MONTHLY_WAGE",
                "percentageOfFullTimeEquivalent": 100.0,
                "annualSalary": 720000.0,
                "occupationCode": {"code": "3512"},
            },
        )

    def test_travel_expense_workflow_posts_resolved_travel_expense(self) -> None:
        prompt = (
            'Erfassen Sie eine Reisekostenabrechnung für Elias Hoffmann '
            '(elias.hoffmann@example.org) für "Kundenbesuch Trondheim" '
            "vom 2026-03-01 bis 2026-03-05. Die Reise dauerte 5 Tage "
            "mit Tagegeld (Tagessatz 800 NOK). "
            "Auslagen: Flight ticket 6300 NOK und Taxi 250 NOK."
        )
        analysis = TaskAnalysis(
            objective=prompt,
            task_family="travelexpense.create",
            operation="create",
            target_resource="travelExpense",
            method_name="RunTravelExpenseWorkflow",
            method_arguments={
                "title": "Kundenbesuch Trondheim",
                "employeeEmail": "elias.hoffmann@example.org",
                "departureDate": "2026-03-01",
                "returnDate": "2026-03-05",
                "perDiemRate": 800,
                "perDiemCount": 5,
                "expenses": [
                    {"description": "Flight ticket", "amount": 6300, "date": "2026-03-01"},
                    {"description": "Taxi", "amount": 250, "date": "2026-03-01"},
                ],
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=prompt, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/employee",
                    "params": {"email": "elias.hoffmann@example.org", "count": 10},
                },
                "response": {
                    "values": [
                        {
                            "id": 55,
                            "email": "elias.hoffmann@example.org",
                            "firstName": "Elias",
                            "lastName": "Hoffmann",
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/travelExpense/paymentType",
                    "params": {
                        "showOnEmployeeExpenses": True,
                        "count": 20,
                        "fields": "id,description,displayName,showOnEmployeeExpenses",
                    },
                },
                "response": {"values": [{"id": 7, "description": "Employee paid"}]},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/travelExpense/costCategory",
                    "params": {
                        "query": "flight",
                        "showOnEmployeeExpenses": True,
                        "count": 20,
                        "fields": "id,description,displayName,showOnEmployeeExpenses",
                    },
                },
                "response": {"values": [{"id": 11, "description": "Flight"}]},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/travelExpense/costCategory",
                    "params": {
                        "query": "taxi",
                        "showOnEmployeeExpenses": True,
                        "count": 20,
                        "fields": "id,description,displayName,showOnEmployeeExpenses",
                    },
                },
                "response": {"values": [{"id": 12, "description": "Taxi"}]},
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=prompt,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/travelExpense")
        self.assertEqual(
            decision.action.json_body,
            {
                "employee": {"id": 55},
                "title": "Kundenbesuch Trondheim",
                "travelDetails": {
                    "departureDate": "2026-03-01",
                    "returnDate": "2026-03-05",
                    "destination": "Kundenbesuch Trondheim",
                    "purpose": "Kundenbesuch Trondheim",
                    "isDayTrip": False,
                },
                "perDiemCompensations": [
                    {
                        "count": 5,
                        "rate": 800.0,
                        "amount": 4000.0,
                        "location": "Kundenbesuch Trondheim",
                    }
                ],
                "costs": [
                    {
                        "date": "2026-03-01",
                        "comments": "Flight ticket",
                        "amountCurrencyIncVat": 6300.0,
                        "costCategory": {"id": 11},
                        "paymentType": {"id": 7},
                    },
                    {
                        "date": "2026-03-01",
                        "comments": "Taxi",
                        "amountCurrencyIncVat": 250.0,
                        "costCategory": {"id": 12},
                        "paymentType": {"id": 7},
                    },
                ],
            },
        )

    def test_travel_expense_delete_workflow_deletes_resolved_report(self) -> None:
        analysis = TaskAnalysis(
            objective="Delete the incorrect travel expense",
            task_family="travelexpense.delete",
            operation="delete",
            target_resource="travelExpense",
            method_name="RunTravelExpenseWorkflow",
            method_arguments={
                "title": "Kundenbesuch Trondheim",
                "employeeEmail": "elias.hoffmann@example.org",
                "departureDate": "2026-03-01",
                "returnDate": "2026-03-05",
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/employee",
                    "params": {"email": "elias.hoffmann@example.org", "count": 10},
                },
                "response": {"values": [{"id": 55, "email": "elias.hoffmann@example.org"}]},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/travelExpense",
                    "params": {
                        "employeeId": 55,
                        "title": "Kundenbesuch Trondheim",
                        "departureDateFrom": "2026-03-01",
                        "returnDateTo": "2026-03-05",
                        "count": 20,
                        "fields": "id,version,title,travelDetails,employee(id)",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 88,
                            "version": 3,
                            "title": "Kundenbesuch Trondheim",
                            "employee": {"id": 55},
                            "travelDetails": {
                                "departureDate": "2026-03-01",
                                "returnDate": "2026-03-05",
                            },
                        }
                    ]
                },
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "DELETE")
        self.assertEqual(decision.action.path, "/travelExpense/88")

    def test_company_openapi_workflow_puts_department_accounting_flag(self) -> None:
        analysis = TaskAnalysis(
            objective="Enable department accounting",
            task_family="department.enable_module",
            operation="update",
            target_resource="company",
            method_name="RunCompanyOpenAPIWorkflow",
            method_arguments={"moduleDepartmentAccounting": True},
            payload_fields={"moduleDepartmentAccounting": True},
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=[],
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "PUT")
        self.assertEqual(decision.action.path, "/company")
        self.assertEqual(decision.action.json_body, {"moduleDepartmentAccounting": True})

    def test_timesheet_openapi_workflow_posts_entry_after_resolving_entities(self) -> None:
        analysis = TaskAnalysis(
            objective="Register timesheet hours",
            task_family="timesheet.create",
            operation="create",
            target_resource="timesheet",
            method_name="RunTimesheetOpenAPIWorkflow",
            method_arguments={},
            search_hints={
                "employeeEmail": "astrid.hansen@example.org",
                "projectName": "Dataplattform Tindra",
                "activityName": "Project work",
                "date": "2026-03-21",
            },
            payload_fields={
                "hours": 7.5,
                "comment": "Workshop",
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/employee",
                    "params": {
                        "email": "astrid.hansen@example.org",
                        "count": 10,
                        "fields": "id,version,firstName,lastName,email,employeeNumber",
                    },
                },
                "response": {"values": [{"id": 10, "email": "astrid.hansen@example.org"}]},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/project",
                    "params": {
                        "name": "Dataplattform Tindra",
                        "count": 10,
                        "fields": "id,name,number,isClosed,customer",
                    },
                },
                "response": {"values": [{"id": 20, "name": "Dataplattform Tindra"}]},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/activity",
                    "params": {
                        "name": "Project work",
                        "count": 10,
                        "fields": "id,name,number,isChargeable,isProjectActivity",
                    },
                },
                "response": {"values": [{"id": 30, "name": "Project work"}]},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/timesheet/entry",
                    "params": {
                        "employeeId": 10,
                        "projectId": 20,
                        "activityId": 30,
                        "dateFrom": "2026-03-21",
                        "dateTo": "2026-03-21",
                        "count": 10,
                        "fields": "id,version,date,hours,projectChargeableHours,comment,chargeable,employee(id),project(id),activity(id)",
                    },
                },
                "response": {"values": []},
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/timesheet/entry")
        self.assertEqual(
            decision.action.json_body,
            {
                "employee": {"id": 10},
                "project": {"id": 20},
                "activity": {"id": 30},
                "date": "2026-03-21",
                "hours": 7.5,
                "projectChargeableHours": 7.5,
                "comment": "Workshop",
            },
        )

    def test_month_end_closing_workflow_posts_first_voucher(self) -> None:
        prompt = (
            "Gjer månavslutninga for mars 2026. Periodiser forskotsbetalt kostnad "
            "(9750 kr per månad frå konto 1710 til konto 6500). "
            "Bokfør månadleg avskriving for eit driftsmiddel med innkjøpskost 191900 kr "
            "og levetid 6 år (lineær avskriving frå konto 6030 til konto 1290). "
            "Bokfør også ei lønnsavsetjing på 50000 kr "
            "(debet lønnskostnad konto 5000, kredit påløpt lønn konto 2900)."
        )
        analysis = TaskAnalysis(
            objective=prompt,
            task_family="ledger.month_end",
            operation="create",
            target_resource="ledger",
            method_name="RunMonthEndClosingWorkflow",
            method_arguments={
                "voucherDate": "2026-03-31",
                "periodLabel": "March 2026",
                "periodizationAmount": 9750,
                "prepaidAccountNumber": "1710",
                "periodizationExpenseAccountNumber": "6500",
                "depreciationAmount": 2665.28,
                "depreciationExpenseAccountNumber": "6030",
                "depreciationAccumulatedAccountNumber": "1290",
                "payrollAccrualAmount": 50000,
                "payrollExpenseAccountNumber": "5000",
                "payrollLiabilityAccountNumber": "2900",
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=prompt, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/ledger/account",
                    "params": {"number": "6500", "count": 10, "fields": "id,number,name"},
                },
                "response": {"values": [{"id": 101, "number": 6500, "name": "Other operating expense"}]},
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/ledger/account",
                    "params": {"number": "1710", "count": 10, "fields": "id,number,name"},
                },
                "response": {"values": [{"id": 102, "number": 1710, "name": "Prepaid expense"}]},
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=prompt,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/ledger/voucher")
        self.assertEqual(
            decision.action.json_body,
            {
                "date": "2026-03-31",
                "description": "Month-end March 2026 - prepaid cost periodization",
                "postings": [
                    {
                        "row": 1,
                        "date": "2026-03-31",
                        "description": "Month-end March 2026 - prepaid cost periodization",
                        "account": {"id": 101},
                        "amountGross": 9750.0,
                        "amountGrossCurrency": 9750.0,
                    },
                    {
                        "row": 2,
                        "date": "2026-03-31",
                        "description": "Month-end March 2026 - prepaid cost periodization",
                        "account": {"id": 102},
                        "amountGross": -9750.0,
                        "amountGrossCurrency": -9750.0,
                    },
                ],
            },
        )

    def test_invoice_payment_workflow_resolves_customer_then_registers_payment(self) -> None:
        analysis = TaskAnalysis(
            objective="Register payment from Havbris AS",
            task_family="invoice.register_payment",
            operation="register_payment",
            target_resource="invoice",
            method_name="RegisterInvoicePayment",
            method_arguments={
                "customerName": "Havbris AS",
                "customerOrganizationNumber": "887674973",
                "paidAmount": 17724,
                "currencyCode": "EUR",
                "paymentDate": "2026-03-21",
                "invoiceAmount": 17724,
                "invoiceDateFrom": "2026-01-01",
                "invoiceDateTo": "2026-12-31",
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/customer",
                    "params": {
                        "organizationNumber": "887674973",
                        "customerName": "Havbris AS",
                        "count": 10,
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 108293070,
                            "name": "Havbris AS",
                            "organizationNumber": "887674973",
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/invoice",
                    "params": {
                        "invoiceDateFrom": "2026-01-01",
                        "invoiceDateTo": "2026-12-31",
                        "customerId": 108293070,
                        "count": 50,
                        "fields": "id,invoiceNumber,amount,amountCurrency,amountExcludingVat,amountExcludingVatCurrency,invoiceDate,invoiceComment,invoiceRemarks,orderLines(description)",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 5001,
                            "invoiceNumber": "2026-1042",
                            "amount": 17724.0,
                            "amountCurrency": 17724.0,
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/invoice/paymentType",
                    "params": {"count": 10},
                },
                "response": {"values": [{"id": 33, "description": "Bank payment"}]},
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "PUT")
        self.assertEqual(decision.action.path, "/invoice/5001/:payment")
        self.assertEqual(
            decision.action.params,
            {
                "paymentDate": "2026-03-21",
                "paymentTypeId": 33,
                "paidAmount": 17724.0,
            },
        )

    def test_expense_increase_project_workflow_creates_first_project(self) -> None:
        analysis = TaskAnalysis(
            objective="Create internal projects for largest expense increases",
            task_family="project.create",
            operation="create",
            target_resource="project",
            method_name="RunExpenseIncreaseProjectWorkflow",
            method_arguments={
                "baselineDateFrom": "2026-01-01",
                "baselineDateTo": "2026-01-31",
                "comparisonDateFrom": "2026-02-01",
                "comparisonDateTo": "2026-02-28",
                "topCount": 3,
                "isInternal": True,
                "createActivity": True,
            },
            missing_required_arguments=[],
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/ledger/posting",
                    "params": {
                        "dateFrom": "2026-01-01",
                        "dateTo": "2026-01-31",
                        "count": 1000,
                        "fields": "amount,account(id,number,name)",
                    },
                },
                "response": {
                    "values": [
                        {"amount": 1000.0, "account": {"id": 1, "number": 6100, "name": "Frakt"}},
                        {"amount": 1200.0, "account": {"id": 2, "number": 6340, "name": "Lys, varme"}},
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/ledger/posting",
                    "params": {
                        "dateFrom": "2026-02-01",
                        "dateTo": "2026-02-28",
                        "count": 1000,
                        "fields": "amount,account(id,number,name)",
                    },
                },
                "response": {
                    "values": [
                        {"amount": 9000.0, "account": {"id": 1, "number": 6100, "name": "Frakt"}},
                        {"amount": 1800.0, "account": {"id": 2, "number": 6340, "name": "Lys, varme"}},
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/project",
                    "params": {"name": "Frakt", "count": 10},
                },
                "response": {"values": []},
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "POST")
        self.assertEqual(decision.action.path, "/project")
        self.assertEqual(decision.action.json_body, {"name": "Frakt", "isInternal": True})

    def test_payment_reversal_reverses_resolved_voucher(self) -> None:
        analysis = TaskAnalysis(
            objective="Reverse returned invoice payment",
            task_family="ledger.reverse",
            operation="reverse",
            target_resource="ledger",
            method_name="RunInvoicePaymentReversalWorkflow",
            method_arguments={},
            search_hints={"customerName": "Ridgepoint Ltd", "customerOrganizationNumber": "990845042"},
            payload_fields={
                "description": "Cloud Storage",
                "amountExcludingVat": "43550",
                "customerName": "Ridgepoint Ltd",
                "customerOrganizationNumber": "990845042",
                "date": "2026-03-21",
            },
        )
        task = derive_internal_task(task_prompt=analysis.objective, task_analysis=analysis)
        history = [
            {
                "request": {
                    "method": "GET",
                    "path": "/customer",
                    "params": {
                        "organizationNumber": "990845042",
                        "customerName": "Ridgepoint Ltd",
                        "count": 10,
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 108310215,
                            "name": "Ridgepoint Ltd",
                            "organizationNumber": "990845042",
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/invoice",
                    "params": {
                        "invoiceDateFrom": "2026-03-21",
                        "invoiceDateTo": "2026-03-21",
                        "customerId": 108310215,
                        "count": 50,
                        "fields": "id,invoiceNumber,amount,amountCurrency,amountExcludingVat,amountExcludingVatCurrency,invoiceDate,invoiceComment,invoiceRemarks,orderLines(description)",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 77,
                            "invoiceNumber": "1001",
                            "amountExcludingVat": 43550.0,
                            "invoiceComment": "Cloud Storage",
                        }
                    ]
                },
            },
            {
                "request": {
                    "method": "GET",
                    "path": "/ledger/posting",
                    "params": {
                        "dateFrom": "2026-03-21",
                        "dateTo": "2026-03-21",
                        "customerId": 108310215,
                        "type": "INCOMING_PAYMENT",
                        "count": 200,
                        "fields": "id,date,type,invoiceNumber,description,amount,voucher(id,description,date,version)",
                    },
                },
                "response": {
                    "values": [
                        {
                            "id": 901,
                            "type": "INCOMING_PAYMENT",
                            "invoiceNumber": "1001",
                            "description": "Payment for Cloud Storage",
                            "amount": -43550.0,
                            "voucher": {"id": 444, "description": "Returned payment"},
                        }
                    ]
                },
            },
        ]

        decision = self.router.next_step(
            internal_task=task,
            task_prompt=analysis.objective,
            task_analysis=analysis,
            history=history,
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.kind, "action")
        self.assertEqual(decision.action.method, "PUT")
        self.assertEqual(decision.action.path, "/ledger/voucher/444/:reverse")
        self.assertEqual(decision.action.params, {"date": "2026-03-21"})


if __name__ == "__main__":
    unittest.main()
