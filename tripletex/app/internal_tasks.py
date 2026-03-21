from __future__ import annotations

import re
from datetime import date, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from .openapi_registry import _resource_prefixes, canonical_resource_family, workflow_resource_families
from .spec_runtime import (
    combine_analysis_text,
    default_action_date,
    is_employee_admin_task,
    is_invoice_payment_task,
    lookup_analysis_value as _legacy_lookup_analysis_value,
)
from .tasking import TASK_ANALYSIS_CONTRACT_VERSION, AttachmentContext, TaskAnalysis


class FlowKind(str, Enum):
    SALES_WORKFLOW = "sales.workflow"
    PROJECT_TIME_INVOICE_WORKFLOW = "project.time_invoice.workflow"
    PROJECT_LIFECYCLE_WORKFLOW = "project.lifecycle.workflow"
    EXPENSE_INCREASE_PROJECT_WORKFLOW = "expense_increase_project.workflow"
    SALARY_PAYROLL_WORKFLOW = "salary.payroll.workflow"
    BANK_RECONCILIATION_WORKFLOW = "bank.reconciliation.workflow"
    SUPPLIER_INVOICE_WORKFLOW = "supplier.invoice.workflow"
    INVOICE_CREDIT_NOTE = "invoice.credit_note"
    INVOICE_REGISTER_PAYMENT = "invoice.register_payment"
    INVOICE_PAYMENT_REVERSAL_WORKFLOW = "invoice.payment_reversal.workflow"
    EMPLOYEE_ADMIN = "employee.admin"
    EMPLOYEE_UPSERT = "employee.upsert"
    EMPLOYEE_ONBOARDING_WORKFLOW = "employee.onboarding.workflow"
    TRAVEL_EXPENSE_WORKFLOW = "travel.expense.workflow"
    MONTH_END_CLOSING_WORKFLOW = "month_end.closing.workflow"
    CUSTOMER_UPSERT = "customer.upsert"
    SUPPLIER_UPSERT = "supplier.upsert"
    PRODUCT_UPSERT = "product.upsert"
    DEPARTMENT_UPSERT = "department.upsert"
    PROJECT_UPSERT = "project.upsert"
    LEDGER_DIMENSION_WORKFLOW = "ledger.dimension.workflow"
    OPENAPI_RESOURCE_WORKFLOW = "openapi.resource.workflow"


CoverageStatus = Literal["coded", "wrapper_only", "unsupported"]


@dataclass(frozen=True)
class MethodSpec:
    name: str
    flow_kind: FlowKind
    operation: str
    target_resource: str
    description: str
    execution_strategy: str = "curated_router"
    coverage_status: CoverageStatus = "coded"
    required_arguments: tuple[str, ...] = ()
    required_one_of: tuple[tuple[str, ...], ...] = ()
    optional_arguments: tuple[str, ...] = ()
    planner_choose_when: tuple[str, ...] = ()
    planner_avoid_when: tuple[str, ...] = ()


METHOD_SPECS: dict[str, MethodSpec] = {
    "CreateCustomer": MethodSpec(
        name="CreateCustomer",
        flow_kind=FlowKind.CUSTOMER_UPSERT,
        operation="create",
        target_resource="customer",
        description="Create a customer from normalized customer fields.",
        required_arguments=("name",),
        optional_arguments=(
            "organizationNumber",
            "email",
            "invoiceEmail",
            "phoneNumber",
            "phoneNumberMobile",
            "description",
        ),
    ),
    "UpsertCustomer": MethodSpec(
        name="UpsertCustomer",
        flow_kind=FlowKind.CUSTOMER_UPSERT,
        operation="update",
        target_resource="customer",
        description="Find or update a customer from normalized customer fields.",
        required_arguments=("name",),
        optional_arguments=(
            "organizationNumber",
            "email",
            "invoiceEmail",
            "phoneNumber",
            "phoneNumberMobile",
            "description",
        ),
    ),
    "CreateSupplier": MethodSpec(
        name="CreateSupplier",
        flow_kind=FlowKind.SUPPLIER_UPSERT,
        operation="create",
        target_resource="supplier",
        description="Create a supplier from normalized supplier fields.",
        required_arguments=("name",),
        optional_arguments=(
            "organizationNumber",
            "email",
            "invoiceEmail",
            "phoneNumber",
            "phoneNumberMobile",
            "description",
        ),
    ),
    "UpsertSupplier": MethodSpec(
        name="UpsertSupplier",
        flow_kind=FlowKind.SUPPLIER_UPSERT,
        operation="update",
        target_resource="supplier",
        description="Find or update a supplier from normalized supplier fields.",
        required_arguments=("name",),
        optional_arguments=(
            "organizationNumber",
            "email",
            "invoiceEmail",
            "phoneNumber",
            "phoneNumberMobile",
            "description",
        ),
    ),
    "CreateProduct": MethodSpec(
        name="CreateProduct",
        flow_kind=FlowKind.PRODUCT_UPSERT,
        operation="create",
        target_resource="product",
        description="Create a product from normalized product fields.",
        required_arguments=("name",),
        optional_arguments=("number", "description", "orderLineDescription", "priceExcludingVat"),
    ),
    "UpsertProduct": MethodSpec(
        name="UpsertProduct",
        flow_kind=FlowKind.PRODUCT_UPSERT,
        operation="update",
        target_resource="product",
        description="Find or update a product from normalized product fields.",
        required_arguments=("name",),
        optional_arguments=("number", "description", "orderLineDescription", "priceExcludingVat"),
    ),
    "CreateEmployee": MethodSpec(
        name="CreateEmployee",
        flow_kind=FlowKind.EMPLOYEE_UPSERT,
        operation="create",
        target_resource="employee",
        description="Create an employee from normalized employee fields.",
        required_arguments=("firstName", "lastName"),
        optional_arguments=(
            "email",
            "employeeNumber",
            "dateOfBirth",
            "nationalIdentityNumber",
            "bankAccountNumber",
            "departmentName",
            "departmentNumber",
            "startDate",
            "employmentForm",
            "remunerationType",
            "occupationCode",
            "percentageOfFullTimeEquivalent",
            "annualSalary",
            "phoneNumberMobile",
            "phoneNumberWork",
            "comments",
            "userType",
        ),
    ),
    "UpsertEmployee": MethodSpec(
        name="UpsertEmployee",
        flow_kind=FlowKind.EMPLOYEE_UPSERT,
        operation="update",
        target_resource="employee",
        description="Find or update an employee from normalized employee fields.",
        required_arguments=("firstName", "lastName"),
        optional_arguments=(
            "email",
            "employeeNumber",
            "dateOfBirth",
            "nationalIdentityNumber",
            "bankAccountNumber",
            "departmentName",
            "departmentNumber",
            "startDate",
            "employmentForm",
            "remunerationType",
            "occupationCode",
            "percentageOfFullTimeEquivalent",
            "annualSalary",
            "phoneNumberMobile",
            "phoneNumberWork",
            "comments",
            "userType",
        ),
    ),
    "GrantEmployeeEntitlements": MethodSpec(
        name="GrantEmployeeEntitlements",
        flow_kind=FlowKind.EMPLOYEE_ADMIN,
        operation="update",
        target_resource="employee",
        description="Grant a named entitlement template to an employee.",
        required_arguments=("template",),
        required_one_of=(("email", "employeeNumber"), ("firstName", "lastName")),
        optional_arguments=("phoneNumberMobile", "phoneNumberWork", "comments"),
    ),
    "CreateDepartment": MethodSpec(
        name="CreateDepartment",
        flow_kind=FlowKind.DEPARTMENT_UPSERT,
        operation="create",
        target_resource="department",
        description="Create a department from normalized department fields.",
        required_arguments=("name",),
        optional_arguments=("departmentNumber",),
    ),
    "UpsertDepartment": MethodSpec(
        name="UpsertDepartment",
        flow_kind=FlowKind.DEPARTMENT_UPSERT,
        operation="update",
        target_resource="department",
        description="Find or update a department from normalized department fields.",
        required_arguments=("name",),
        optional_arguments=("departmentNumber",),
    ),
    "CreateProject": MethodSpec(
        name="CreateProject",
        flow_kind=FlowKind.PROJECT_UPSERT,
        operation="create",
        target_resource="project",
        description="Create a project from normalized project fields and related references.",
        required_arguments=("name",),
        optional_arguments=(
            "number",
            "description",
            "reference",
            "startDate",
            "endDate",
            "invoiceReceiverEmail",
            "overdueNoticeEmail",
            "isFixedPrice",
            "fixedPrice",
            "customerOrganizationNumber",
            "customerName",
            "departmentNumber",
            "departmentName",
            "projectManagerEmail",
            "projectManagerFirstName",
            "projectManagerLastName",
        ),
    ),
    "UpsertProject": MethodSpec(
        name="UpsertProject",
        flow_kind=FlowKind.PROJECT_UPSERT,
        operation="update",
        target_resource="project",
        description="Find or update a project from normalized project fields and related references.",
        required_arguments=("name",),
        optional_arguments=(
            "number",
            "description",
            "reference",
            "startDate",
            "endDate",
            "invoiceReceiverEmail",
            "overdueNoticeEmail",
            "isFixedPrice",
            "fixedPrice",
            "customerOrganizationNumber",
            "customerName",
            "departmentNumber",
            "departmentName",
            "projectManagerEmail",
            "projectManagerFirstName",
            "projectManagerLastName",
        ),
    ),
    "RunSalesWorkflow": MethodSpec(
        name="RunSalesWorkflow",
        flow_kind=FlowKind.SALES_WORKFLOW,
        operation="invoice",
        target_resource="invoice",
        description="Create an order and optionally invoice it and register payment.",
        required_arguments=("orderLines",),
        required_one_of=(("customerOrganizationNumber", "customerName"),),
        optional_arguments=(
            "orderDate",
            "deliveryDate",
            "invoiceDate",
            "invoiceDueDate",
            "paymentDate",
            "paymentTypeDescription",
            "createInvoice",
            "registerPayment",
        ),
        planner_choose_when=(
            "Use when the task is a sales flow that creates an order, invoice, or invoice plus payment from customer and order-line data.",
            "Use for customer -> order -> invoice flows and simple create-with-linking invoice requests.",
        ),
        planner_avoid_when=(
            "Do not use for timesheet-based project invoicing.",
            "Do not use for supplier invoices, credit notes, payment reversals, or ledger correction tasks.",
        ),
    ),
    "RunProjectTimeInvoiceWorkflow": MethodSpec(
        name="RunProjectTimeInvoiceWorkflow",
        flow_kind=FlowKind.PROJECT_TIME_INVOICE_WORKFLOW,
        operation="invoice",
        target_resource="invoice",
        description="Resolve or create the customer, employee, project, and activity; register timesheet hours; then create and invoice an order line from those logged hours.",
        required_arguments=("hours", "hourlyRate"),
        required_one_of=(
            ("customerOrganizationNumber", "customerName"),
            ("projectName", "projectNumber"),
            ("activityName", "activityNumber"),
        ),
        optional_arguments=(
            "customerName",
            "customerOrganizationNumber",
            "employeeEmail",
            "employeeFirstName",
            "employeeLastName",
            "projectName",
            "projectNumber",
            "activityName",
            "activityNumber",
            "date",
            "comment",
            "invoiceDate",
            "invoiceDueDate",
            "orderDate",
            "deliveryDate",
        ),
        planner_choose_when=(
            "Use when the request bills a project from hours, timesheet entries, activities, hourly rates, or registered work.",
            "Use when the workflow must resolve employee, project, activity, register hours, then invoice them.",
        ),
        planner_avoid_when=(
            "Do not use for ordinary sales invoices without time tracking.",
            "Do not use for full project lifecycle workflows that also include supplier costs.",
        ),
    ),
    "RunProjectLifecycleWorkflow": MethodSpec(
        name="RunProjectLifecycleWorkflow",
        flow_kind=FlowKind.PROJECT_LIFECYCLE_WORKFLOW,
        operation="other",
        target_resource="project",
        description=(
            "Execute a full project lifecycle workflow: resolve the customer and project, register project hours, "
            "register supplier costs, and create the customer invoice."
        ),
        optional_arguments=(
            "projectName",
            "projectNumber",
            "projectBudget",
            "customerName",
            "customerOrganizationNumber",
            "projectManagerEmail",
            "projectManagerFirstName",
            "projectManagerLastName",
            "activityName",
            "timesheetEntries",
            "supplierName",
            "supplierOrganizationNumber",
            "supplierInvoiceNumber",
            "supplierInvoiceDescription",
            "supplierInvoiceAmountIncludingVat",
            "supplierAccountNumber",
            "vatRate",
            "invoiceDate",
            "invoiceDueDate",
        ),
        planner_choose_when=(
            "Use when one task spans customer, project, timesheets, supplier costs, and customer invoicing together.",
            "Use for full project lifecycle requests with prerequisites and linked follow-up actions.",
        ),
        planner_avoid_when=(
            "Do not use for simple project create/update tasks.",
            "Do not use for project-hour invoicing unless supplier-cost lifecycle steps are also required.",
        ),
    ),
    "RegisterSupplierInvoice": MethodSpec(
        name="RegisterSupplierInvoice",
        flow_kind=FlowKind.SUPPLIER_INVOICE_WORKFLOW,
        operation="create",
        target_resource="supplierinvoice",
        description="Register a supplier invoice using the incoming-invoice API with resolved supplier, account, and VAT.",
        optional_arguments=(
            "supplierName",
            "supplierOrganizationNumber",
            "supplierEmail",
            "invoiceNumber",
            "description",
            "accountNumber",
            "amountIncludingVat",
            "vatRate",
            "invoiceDate",
            "dueDate",
            "voucherTypeName",
        ),
        planner_choose_when=(
            "Use when registering an incoming or supplier invoice with supplier identity, invoice number, account, VAT, and amounts.",
            "Use for supplier invoice tasks even when the supplier must be resolved or created first.",
        ),
        planner_avoid_when=(
            "Do not use for ordinary supplier create/update without an invoice.",
            "Do not use for outgoing customer invoices.",
        ),
    ),
    "CreateInvoiceCreditNote": MethodSpec(
        name="CreateInvoiceCreditNote",
        flow_kind=FlowKind.INVOICE_CREDIT_NOTE,
        operation="reverse",
        target_resource="invoice",
        description="Find an outgoing invoice and create a full credit note from it.",
        optional_arguments=(
            "customerName",
            "customerOrganizationNumber",
            "invoiceNumber",
            "description",
            "amountExcludingVat",
            "creditNoteDate",
            "comment",
        ),
        planner_choose_when=(
            "Use when the request is to credit, cancel with a credit note, or reverse an outgoing invoice by issuing a credit note.",
        ),
        planner_avoid_when=(
            "Do not use for registering invoice payments.",
            "Do not use for reversing a payment voucher back to an open invoice.",
        ),
    ),
    "RegisterInvoicePayment": MethodSpec(
        name="RegisterInvoicePayment",
        flow_kind=FlowKind.INVOICE_REGISTER_PAYMENT,
        operation="register_payment",
        target_resource="invoice",
        description="Register payment on an outgoing invoice.",
        required_arguments=("paidAmount",),
        required_one_of=(("invoiceNumber", "customerId", "customerOrganizationNumber", "customerName"),),
        optional_arguments=(
            "paymentDate",
            "paymentTypeDescription",
            "paymentTypeId",
            "customerName",
            "customerOrganizationNumber",
            "invoiceAmount",
            "currencyCode",
            "invoiceDateFrom",
            "invoiceDateTo",
        ),
        planner_choose_when=(
            "Use when registering an outgoing invoice payment, including currency settlement and agio/disagio scenarios.",
            "Use when invoiceNumber is missing but the customer and invoice amount can resolve the invoice deterministically.",
        ),
        planner_avoid_when=(
            "Do not use for reversing an already registered payment.",
            "Do not use for credit notes or supplier-invoice payments.",
        ),
    ),
    "RunInvoicePaymentReversalWorkflow": MethodSpec(
        name="RunInvoicePaymentReversalWorkflow",
        flow_kind=FlowKind.INVOICE_PAYMENT_REVERSAL_WORKFLOW,
        operation="reverse",
        target_resource="ledger",
        description=(
            "Reverse the ledger voucher for a returned or wrongly registered invoice payment so the invoice becomes "
            "outstanding again."
        ),
        optional_arguments=(
            "customerName",
            "customerOrganizationNumber",
            "invoiceNumber",
            "description",
            "amountExcludingVat",
            "reversalDate",
            "comment",
        ),
        planner_choose_when=(
            "Use when the request is to reverse, undo, or cancel an already registered outgoing invoice payment.",
        ),
        planner_avoid_when=(
            "Do not use for first-time invoice payment registration.",
            "Do not use for credit-note creation.",
        ),
    ),
    "CreateLedgerDimensionWorkflow": MethodSpec(
        name="CreateLedgerDimensionWorkflow",
        flow_kind=FlowKind.LEDGER_DIMENSION_WORKFLOW,
        operation="create",
        target_resource="ledger",
        description="Create a free accounting dimension and one or more dimension values.",
        required_arguments=("dimensionName", "dimensionValues"),
        optional_arguments=(
            "postingAccount",
            "postingAmount",
            "postingDimensionValue",
            "counterAccount",
            "voucherDate",
            "voucherDescription",
            "currencyCode",
            "requiresVoucher",
        ),
        planner_choose_when=(
            "Use when creating accounting dimensions or dimension values and optionally posting a balancing voucher for them.",
        ),
        planner_avoid_when=(
            "Do not use for general month-end closing, travel expenses, or invoice flows.",
        ),
    ),
    "RunEmployeeOnboardingWorkflow": MethodSpec(
        name="RunEmployeeOnboardingWorkflow",
        flow_kind=FlowKind.EMPLOYEE_ONBOARDING_WORKFLOW,
        operation="create",
        target_resource="employee",
        description=(
            "Create or update an employee together with employment records and employment details such as department, "
            "employment form, remuneration type, occupation code, salary, and start date."
        ),
        optional_arguments=(
            "firstName",
            "lastName",
            "email",
            "employeeNumber",
            "dateOfBirth",
            "nationalIdentityNumber",
            "bankAccountNumber",
            "departmentName",
            "departmentNumber",
            "startDate",
            "employmentForm",
            "remunerationType",
            "occupationCode",
            "percentageOfFullTimeEquivalent",
            "annualSalary",
            "hourlyWage",
            "userType",
            "comments",
        ),
        planner_choose_when=(
            "Use when creating an employee from an employment contract or when employment details like department, occupation code, salary, start date, and employment form are part of the request.",
            "Use attachment-driven employee onboarding tasks.",
        ),
        planner_avoid_when=(
            "Do not use for simple contact-info corrections that only update an existing employee record.",
            "Do not use for entitlement-only or role-only admin tasks.",
        ),
    ),
    "RunTravelExpenseWorkflow": MethodSpec(
        name="RunTravelExpenseWorkflow",
        flow_kind=FlowKind.TRAVEL_EXPENSE_WORKFLOW,
        operation="create",
        target_resource="travelExpense",
        description=(
            "Create a travel expense with resolved employee, travel dates, per diem compensation, and travel costs."
        ),
        required_arguments=("title", "departureDate", "returnDate"),
        optional_arguments=(
            "employeeEmail",
            "employeeFirstName",
            "employeeLastName",
            "employeeNumber",
            "durationDays",
            "destination",
            "perDiemRate",
            "perDiemCount",
            "expenses",
        ),
        planner_choose_when=(
            "Use when creating, updating, or deleting travel expenses, travel expense reports, per diem entries, or travel-cost claims.",
            "Use when the task includes employee identity, trip title, dates or duration, per diem, and expense lines.",
        ),
        planner_avoid_when=(
            "Do not use for invoice, voucher, or project-timesheet workflows.",
        ),
    ),
    "RunMonthEndClosingWorkflow": MethodSpec(
        name="RunMonthEndClosingWorkflow",
        flow_kind=FlowKind.MONTH_END_CLOSING_WORKFLOW,
        operation="create",
        target_resource="ledger",
        description=(
            "Create month-end closing vouchers for periodization, depreciation, and payroll accrual when the "
            "prompt supplies all required account numbers and amounts."
        ),
        required_arguments=(
            "voucherDate",
            "periodizationAmount",
            "prepaidAccountNumber",
            "periodizationExpenseAccountNumber",
            "depreciationAmount",
            "depreciationExpenseAccountNumber",
            "depreciationAccumulatedAccountNumber",
            "payrollAccrualAmount",
            "payrollExpenseAccountNumber",
            "payrollLiabilityAccountNumber",
        ),
        optional_arguments=("periodLabel", "verifyTrialBalance"),
        planner_choose_when=(
            "Use for month-end closing requests involving prepaid-cost periodization, depreciation, payroll accruals, and trial-balance verification.",
            "Use when the prompt supplies the needed voucher dates, account numbers, and accounting amounts.",
        ),
        planner_avoid_when=(
            "Do not use for generic ledger CRUD tasks or single voucher updates.",
        ),
    ),
    "RunExpenseIncreaseProjectWorkflow": MethodSpec(
        name="RunExpenseIncreaseProjectWorkflow",
        flow_kind=FlowKind.EXPENSE_INCREASE_PROJECT_WORKFLOW,
        operation="create",
        target_resource="project",
        description=(
            "Compare two monthly ledger periods, identify the expense accounts with the largest increase, and create "
            "matching internal projects and activities."
        ),
        required_arguments=("baselineDateFrom", "baselineDateTo", "comparisonDateFrom", "comparisonDateTo"),
        optional_arguments=("topCount", "isInternal", "createActivity"),
        planner_choose_when=(
            "Use when the task compares two periods, finds the largest expense-account increases, and creates internal projects or activities from those accounts.",
        ),
        planner_avoid_when=(
            "Do not use for ordinary project create/update requests unrelated to ledger analysis.",
        ),
    ),
    "RunSalaryPayrollWorkflow": MethodSpec(
        name="RunSalaryPayrollWorkflow",
        flow_kind=FlowKind.SALARY_PAYROLL_WORKFLOW,
        operation="create",
        target_resource="salary",
        description=(
            "Create a salary transaction and payslip specifications for a concrete payroll period after resolving the "
            "employee and referenced salary types."
        ),
        required_arguments=("date", "month", "year"),
        optional_arguments=(
            "employeeEmail",
            "employeeFirstName",
            "employeeLastName",
            "salaryLines",
            "payslips",
            "paySlipsAvailableDate",
            "isHistorical",
            "generateTaxDeduction",
        ),
        planner_choose_when=(
            "Use when the task is to run payroll, create salary transactions, or register salary and bonus lines for an employee.",
            "Use when the request describes a monthly salary run, base salary, bonus, wage, or compensation to be posted as payroll.",
        ),
        planner_avoid_when=(
            "Do not use for salary settings, reconciliation reports, or salary-module configuration tasks unrelated to creating payslips.",
        ),
    ),
    "RunBankReconciliationWorkflow": MethodSpec(
        name="RunBankReconciliationWorkflow",
        flow_kind=FlowKind.BANK_RECONCILIATION_WORKFLOW,
        operation="other",
        target_resource="bank",
        description=(
            "Match structured bank-statement entries against outgoing and supplier invoices and register the resulting "
            "payments deterministically."
        ),
        optional_arguments=(
            "statementEntries",
            "fromDate",
            "toDate",
            "bankAccountNumber",
            "bankRegisterNumber",
            "bankName",
        ),
        planner_choose_when=(
            "Use when reconciling an attached bank statement or CSV against outgoing invoices or supplier invoices.",
            "Use when the request asks to match incoming and outgoing bank transactions to open invoices and handle partial payments.",
        ),
        planner_avoid_when=(
            "Do not use for simple bank lookups, bank settings, or generic bank CRUD tasks unrelated to invoice matching.",
        ),
    ),
}


def _openapi_workflow_method_name(resource_family: str) -> str:
    canonical_family = canonical_resource_family(resource_family)
    label_lookup = dict(workflow_resource_families())
    label = label_lookup.get(canonical_family, "Generic")
    return f"Run{label}OpenAPIWorkflow"


def _build_openapi_resource_workflow_specs() -> dict[str, MethodSpec]:
    specs: dict[str, MethodSpec] = {}
    for resource_family, label in workflow_resource_families():
        method_name = f"Run{label}OpenAPIWorkflow"
        specs[method_name] = MethodSpec(
            name=method_name,
            flow_kind=FlowKind.OPENAPI_RESOURCE_WORKFLOW,
            operation="other",
            target_resource=resource_family,
            description=(
                f"Execute a {label} task through the OpenAPI workflow wrapper when no narrower curated workflow "
                "covers the request."
            ),
            execution_strategy="openapi_wrapper",
            coverage_status="wrapper_only",
            planner_choose_when=(
                "Use only when no narrower curated workflow covers the request and the task can be executed as deterministic resource-shaped CRUD, lookup, delete, reverse, or update.",
            ),
            planner_avoid_when=(
                "Do not use when a curated_router method already matches the requested business workflow.",
            ),
        )
    return specs


_OPENAPI_RESOURCE_WORKFLOW_SPECS = _build_openapi_resource_workflow_specs()
METHOD_SPECS.update(_OPENAPI_RESOURCE_WORKFLOW_SPECS)

_WORKFLOW_METHOD_PREFIX_OVERRIDES: dict[str, tuple[str, ...]] = {
    "RunEmployeeOnboardingWorkflow": ("/employee", "/department", "/documentArchive"),
    "RunTravelExpenseWorkflow": (
        "/employee",
        "/travelExpense",
        "/travelExpense/costCategory",
        "/travelExpense/paymentType",
    ),
    "RunMonthEndClosingWorkflow": ("/ledger/account", "/ledger/voucher"),
    "RunExpenseIncreaseProjectWorkflow": ("/ledger/posting", "/project", "/activity"),
    "RunSalaryPayrollWorkflow": ("/employee", "/salary/type", "/salary/transaction"),
    "RunBankReconciliationWorkflow": (
        "/invoice",
        "/invoice/paymentType",
        "/customer",
        "/supplier",
        "/incomingInvoice",
        "/supplierInvoice",
    ),
    "RunInvoicePaymentReversalWorkflow": ("/customer", "/invoice", "/ledger"),
    "RunProjectLifecycleWorkflow": (
        "/customer",
        "/project",
        "/employee",
        "/activity",
        "/timesheet",
        "/supplier",
        "/incomingInvoice",
        "/order",
        "/invoice",
        "/ledger",
    ),
}


def _is_openapi_workflow_method(method_name: str) -> bool:
    return method_name in _OPENAPI_RESOURCE_WORKFLOW_SPECS


@dataclass(frozen=True)
class InternalTask:
    method_name: str
    flow_kind: FlowKind
    operation: str
    target_resource: str
    objective: str
    search: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def is_supported(self) -> bool:
        return self.method_name in METHOD_SPECS


def planner_method_hints() -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for spec in METHOD_SPECS.values():
        hints.append(
            {
                "method_name": spec.name,
                "description": spec.description,
                "required_arguments": list(spec.required_arguments),
                "required_one_of": [list(group) for group in spec.required_one_of],
                "optional_arguments": list(spec.optional_arguments),
                "operation": spec.operation,
                "target_resource": spec.target_resource,
                "execution_strategy": spec.execution_strategy,
                "coverage_status": spec.coverage_status,
                "planner_choose_when": list(spec.planner_choose_when),
                "planner_avoid_when": list(spec.planner_avoid_when),
            }
        )
    return hints


def method_coverage_snapshot() -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for spec in sorted(METHOD_SPECS.values(), key=lambda item: item.name):
        snapshot.append(
            {
                "method_name": spec.name,
                "flow_kind": spec.flow_kind.value,
                "target_resource": spec.target_resource,
                "operation": spec.operation,
                "execution_strategy": spec.execution_strategy,
                "coverage_status": spec.coverage_status,
            }
        )
    return snapshot


def documented_task_category_coverage() -> dict[str, bool]:
    coded_families = {spec.flow_kind for spec in METHOD_SPECS.values() if spec.coverage_status == "coded"}
    return {
        "employees": bool(coded_families & {FlowKind.EMPLOYEE_UPSERT, FlowKind.EMPLOYEE_ONBOARDING_WORKFLOW, FlowKind.EMPLOYEE_ADMIN}),
        "customers_products": bool(coded_families & {FlowKind.CUSTOMER_UPSERT, FlowKind.PRODUCT_UPSERT}),
        "invoicing": bool(
            coded_families
            & {
                FlowKind.SALES_WORKFLOW,
                FlowKind.SUPPLIER_INVOICE_WORKFLOW,
                FlowKind.INVOICE_CREDIT_NOTE,
                FlowKind.INVOICE_REGISTER_PAYMENT,
                FlowKind.INVOICE_PAYMENT_REVERSAL_WORKFLOW,
            }
        ),
        "travel_expenses": any(
            spec.target_resource == "travelExpense" and spec.coverage_status == "coded" for spec in METHOD_SPECS.values()
        ),
        "projects": bool(coded_families & {FlowKind.PROJECT_UPSERT, FlowKind.PROJECT_LIFECYCLE_WORKFLOW, FlowKind.PROJECT_TIME_INVOICE_WORKFLOW, FlowKind.EXPENSE_INCREASE_PROJECT_WORKFLOW}),
        "corrections": bool(coded_families & {FlowKind.INVOICE_CREDIT_NOTE, FlowKind.INVOICE_PAYMENT_REVERSAL_WORKFLOW}),
        "departments": bool(coded_families & {FlowKind.DEPARTMENT_UPSERT, FlowKind.LEDGER_DIMENSION_WORKFLOW}),
        "salary": bool(coded_families & {FlowKind.SALARY_PAYROLL_WORKFLOW}),
        "bank_reconciliation": bool(coded_families & {FlowKind.BANK_RECONCILIATION_WORKFLOW}),
    }


def documented_task_category_gaps() -> list[str]:
    coverage = documented_task_category_coverage()
    return [category for category, covered in coverage.items() if not covered]


def startup_coverage_audit_lines() -> list[str]:
    coded = 0
    wrapper_only = 0
    unsupported = 0
    for spec in METHOD_SPECS.values():
        if spec.coverage_status == "coded":
            coded += 1
        elif spec.coverage_status == "wrapper_only":
            wrapper_only += 1
        else:
            unsupported += 1
    gaps = documented_task_category_gaps()
    lines = [
        f"tasking.coverage.summary contract_version={TASK_ANALYSIS_CONTRACT_VERSION} methods={len(METHOD_SPECS)} coded={coded} wrapper_only={wrapper_only} unsupported={unsupported}",
    ]
    if gaps:
        lines.append(f"tasking.coverage.documented_gaps categories={gaps}")
    else:
        lines.append("tasking.coverage.documented_gaps categories=[]")
    return lines


def validate_task_analysis_contract(task_analysis: TaskAnalysis) -> None:
    if task_analysis.contract_version != TASK_ANALYSIS_CONTRACT_VERSION:
        raise ValueError(
            f"Unsupported planner contract version: {task_analysis.contract_version!r}. "
            f"Expected {TASK_ANALYSIS_CONTRACT_VERSION!r}."
        )
    method_name = _normalize_method_name(task_analysis.method_name)
    method_spec = METHOD_SPECS.get(method_name)
    if method_spec is None:
        raise ValueError(f"Planner selected unknown method_name={task_analysis.method_name!r}.")
    combined_text = combine_analysis_text(task_analysis)
    expected_method_name = _expected_planner_method_name(task_analysis=task_analysis, combined_text=combined_text)
    expected_spec = METHOD_SPECS.get(expected_method_name)
    if (
        expected_spec is not None
        and (
            method_spec.flow_kind is not expected_spec.flow_kind
            or canonical_resource_family(method_spec.target_resource)
            != canonical_resource_family(expected_spec.target_resource)
        )
    ):
        raise ValueError(
            "Planner selected a method_name that does not match the structured task analysis. "
            f"expected_method_name={expected_method_name!r} selected_method_name={method_name!r} "
            f"task_family={task_analysis.task_family!r} operation={task_analysis.operation!r} "
            f"target_resource={task_analysis.target_resource!r}"
        )
    if method_spec.flow_kind is FlowKind.OPENAPI_RESOURCE_WORKFLOW:
        expected_resource = canonical_resource_family(method_spec.target_resource)
        selected_resource = canonical_resource_family(task_analysis.target_resource)
        if expected_resource == "other" and selected_resource != "other":
            raise ValueError(
                "Planner selected the generic OpenAPI wrapper even though a family-specific wrapper is available. "
                f"method_name={method_name!r} target_resource={task_analysis.target_resource!r}"
            )
        if expected_resource != "other" and selected_resource not in {"other", expected_resource}:
            raise ValueError(
                "Planner selected an OpenAPI wrapper whose resource family does not match the declared target_resource. "
                f"method_name={method_name!r} target_resource={task_analysis.target_resource!r}"
            )
    if _should_reject_supported_method(
        method_name=method_name,
        task_analysis=task_analysis,
        combined_text=combined_text,
    ):
        raise ValueError(
            "Planner selected a semantically incompatible supported method. "
            f"selected_method_name={method_name!r} task_family={task_analysis.task_family!r} "
            f"target_resource={task_analysis.target_resource!r}"
        )


def workflow_prefixes_for_method(
    method_name: str,
    *,
    task_analysis: TaskAnalysis | None = None,
) -> tuple[str, ...]:
    prefixes: list[str] = []
    seen: set[str] = set()

    def add(prefix: str) -> None:
        if prefix in seen:
            return
        seen.add(prefix)
        prefixes.append(prefix)

    for prefix in _WORKFLOW_METHOD_PREFIX_OVERRIDES.get(method_name, ()):
        add(prefix)

    method_spec = METHOD_SPECS.get(method_name)
    if method_spec is not None:
        for prefix in _resource_prefixes(method_spec.target_resource):
            add(prefix)

    if task_analysis is not None and task_analysis.target_resource:
        for prefix in _resource_prefixes(task_analysis.target_resource):
            add(prefix)

    return tuple(prefixes)


def normalize_task_analysis_method_selection(
    *,
    task_analysis: TaskAnalysis,
    task_prompt: str | None = None,
) -> TaskAnalysis:
    del task_prompt
    normalized_method_name = _normalize_method_name(task_analysis.method_name)
    if normalized_method_name == task_analysis.method_name:
        return task_analysis
    return task_analysis.model_copy(update={"method_name": normalized_method_name})


def resolved_missing_required_arguments(
    task_analysis: TaskAnalysis,
    *,
    method_name: str | None = None,
    internal_payload: dict[str, Any] | None = None,
) -> list[str]:
    explicit_missing = [value for value in task_analysis.missing_required_arguments if str(value).strip()]
    resolved_method_name = _normalize_method_name(method_name or task_analysis.method_name)
    spec = METHOD_SPECS.get(resolved_method_name)
    if spec is None:
        return _dedupe_strings(explicit_missing)

    missing = list(explicit_missing)
    method_arguments = task_analysis.method_arguments or {}
    for key in spec.required_arguments:
        value = _lookup_method_argument(method_arguments, key)
        if _is_missing_required_argument(value):
            value = lookup_analysis_value(task_analysis, key)
        if _is_missing_required_argument(value):
            missing.append(key)
    for group in spec.required_one_of:
        if any(not _is_missing_required_argument(_lookup_method_argument(method_arguments, key)) for key in group):
            continue
        if any(not _is_missing_required_argument(lookup_analysis_value(task_analysis, key)) for key in group):
            continue
        missing.append(" | ".join(group))
    if resolved_method_name == "RunProjectTimeInvoiceWorkflow":
        employee_email = _lookup_method_argument(method_arguments, "employeeEmail")
        if _is_missing_required_argument(employee_email):
            employee_email = lookup_analysis_value(task_analysis, "employeeEmail", "employee_email")
        employee_first_name = _lookup_method_argument(method_arguments, "employeeFirstName")
        if _is_missing_required_argument(employee_first_name):
            employee_first_name = lookup_analysis_value(task_analysis, "employeeFirstName", "firstName", "first_name")
        employee_last_name = _lookup_method_argument(method_arguments, "employeeLastName")
        if _is_missing_required_argument(employee_last_name):
            employee_last_name = lookup_analysis_value(task_analysis, "employeeLastName", "lastName", "last_name")
        if _is_missing_required_argument(employee_email) and (
            _is_missing_required_argument(employee_first_name) or _is_missing_required_argument(employee_last_name)
        ):
            missing.append("employeeEmail | (employeeFirstName + employeeLastName)")
    if resolved_method_name == "RunTravelExpenseWorkflow":
        employee_email = _lookup_method_argument(method_arguments, "employeeEmail")
        if _is_missing_required_argument(employee_email):
            employee_email = lookup_analysis_value(task_analysis, "employeeEmail", "email")
        employee_first_name = _lookup_method_argument(method_arguments, "employeeFirstName")
        if _is_missing_required_argument(employee_first_name):
            employee_first_name = lookup_analysis_value(task_analysis, "employeeFirstName", "firstName", "first_name")
        employee_last_name = _lookup_method_argument(method_arguments, "employeeLastName")
        if _is_missing_required_argument(employee_last_name):
            employee_last_name = lookup_analysis_value(task_analysis, "employeeLastName", "lastName", "last_name")
        if _is_missing_required_argument(employee_email) and (
            _is_missing_required_argument(employee_first_name) or _is_missing_required_argument(employee_last_name)
        ):
            missing.append("employeeEmail | (employeeFirstName + employeeLastName)")
        if (task_analysis.operation or "").lower() == "delete":
            missing = [
                item
                for item in missing
                if item not in {"title", "departureDate", "returnDate"}
            ]
    if resolved_method_name == "RegisterInvoicePayment":
        payment_date = internal_payload.get("paymentDate") if internal_payload else None
        if _is_missing_required_argument(payment_date):
            payment_date = default_action_date(task_analysis, "paymentDate", "date")
        has_invoice_lookup = any(
            not _is_missing_required_argument(value)
            for value in (
                _lookup_method_argument(method_arguments, "invoiceNumber"),
                _lookup_method_argument(method_arguments, "customerId"),
                _lookup_method_argument(method_arguments, "customerOrganizationNumber"),
                _lookup_method_argument(method_arguments, "customerName"),
                lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number"),
                lookup_analysis_value(task_analysis, "customerId", "customer_id"),
                lookup_analysis_value(task_analysis, "customerOrganizationNumber", "organizationNumber"),
                lookup_analysis_value(task_analysis, "customerName", "customer_name", "name"),
            )
        )
        filtered: list[str] = []
        for item in missing:
            if item == "paymentDate" and not _is_missing_required_argument(payment_date):
                continue
            if has_invoice_lookup and item in {
                "invoiceNumber",
                "customerId",
                "invoiceNumber | customerId | customerOrganizationNumber | customerName",
            }:
                continue
            filtered.append(item)
        missing = filtered
    if resolved_method_name == "RunSalaryPayrollWorkflow":
        has_employee_identity = any(
            not _is_missing_required_argument(value)
            for value in (
                _lookup_method_argument(method_arguments, "employeeEmail"),
                _lookup_method_argument(method_arguments, "employeeFirstName"),
                _lookup_method_argument(method_arguments, "employeeLastName"),
                lookup_analysis_value(task_analysis, "employeeEmail", "email"),
                lookup_analysis_value(task_analysis, "employeeFirstName", "firstName"),
                lookup_analysis_value(task_analysis, "employeeLastName", "lastName"),
            )
        )
        if not has_employee_identity:
            missing.append("employeeEmail | (employeeFirstName + employeeLastName)")
        if not _salary_payroll_lines(task_analysis):
            missing.append("salaryLines")
    if resolved_method_name == "RunBankReconciliationWorkflow":
        entries = _bank_statement_entries(task_analysis)
        if not entries:
            missing.append("statementEntries")
        else:
            if not any(not _is_missing_required_argument(entry.get("paymentDate")) for entry in entries):
                missing.append("statementEntries.paymentDate")
            if not any(not _is_missing_required_argument(entry.get("amount")) for entry in entries):
                missing.append("statementEntries.amount")
    if resolved_method_name == "CreateLedgerDimensionWorkflow" and internal_payload:
        requires_voucher = bool(internal_payload.get("requiresVoucher"))
        if requires_voucher:
            for key in ("postingAccount", "postingAmount", "postingDimensionValue", "counterAccount"):
                value = internal_payload.get(key)
                if _is_missing_required_argument(value):
                    value = lookup_analysis_value(task_analysis, key)
                if _is_missing_required_argument(value):
                    missing.append(key)
    return _dedupe_strings(missing)


def lookup_analysis_value(task_analysis: TaskAnalysis, *keys: str) -> Any | None:
    value = _lookup_method_argument(task_analysis.method_arguments or {}, *keys)
    if not _is_blank(value):
        return value
    return _legacy_lookup_analysis_value(task_analysis, *keys)


def derive_internal_task(*, task_analysis: TaskAnalysis, task_prompt: str | None = None) -> InternalTask:
    del task_prompt
    task_analysis = normalize_task_analysis_method_selection(task_analysis=task_analysis)
    combined_text = combine_analysis_text(task_analysis)
    extracted_method_name = _normalize_method_name(task_analysis.method_name)
    method_spec = METHOD_SPECS.get(extracted_method_name)

    if method_spec is not None:
        method_name = method_spec.name
        flow_kind = method_spec.flow_kind
        analyzed_operation = (task_analysis.operation or "").lower()
        operation = method_spec.operation
        if analyzed_operation and method_spec.flow_kind in {
            FlowKind.OPENAPI_RESOURCE_WORKFLOW,
            FlowKind.TRAVEL_EXPENSE_WORKFLOW,
        }:
            operation = analyzed_operation
        target_resource = method_spec.target_resource
    else:
        flow_kind = _infer_flow_kind(task_analysis=task_analysis, combined_text=combined_text)
        operation = (task_analysis.operation or "other").lower()
        target_resource = canonical_resource_family(task_analysis.target_resource)
        method_name = _default_supported_method_name(
            flow_kind=flow_kind,
            operation=operation,
            target_resource=target_resource,
            task_analysis=task_analysis,
        )

    search: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    notes: list[str] = []

    if flow_kind is FlowKind.CUSTOMER_UPSERT:
        search = _customer_search(task_analysis)
        payload = _customer_payload(task_analysis)
    elif flow_kind is FlowKind.SUPPLIER_UPSERT:
        search = _supplier_search(task_analysis)
        payload = _supplier_payload(task_analysis)
    elif flow_kind is FlowKind.PRODUCT_UPSERT:
        search = _product_search(task_analysis)
        payload = _product_payload(task_analysis)
    elif flow_kind is FlowKind.EMPLOYEE_ONBOARDING_WORKFLOW:
        search = _employee_search(task_analysis)
        payload = _employee_onboarding_payload(task_analysis)
    elif flow_kind is FlowKind.TRAVEL_EXPENSE_WORKFLOW:
        search = _travel_expense_search(task_analysis)
        payload = _travel_expense_payload(task_analysis)
    elif flow_kind is FlowKind.EXPENSE_INCREASE_PROJECT_WORKFLOW:
        payload = _expense_increase_project_payload(task_analysis)
    elif flow_kind is FlowKind.SALARY_PAYROLL_WORKFLOW:
        search = _salary_payroll_search(task_analysis)
        payload = _salary_payroll_payload(task_analysis)
    elif flow_kind is FlowKind.BANK_RECONCILIATION_WORKFLOW:
        search = _bank_reconciliation_search(task_analysis)
        payload = _bank_reconciliation_payload(task_analysis)
    elif flow_kind is FlowKind.MONTH_END_CLOSING_WORKFLOW:
        payload = _month_end_closing_payload(task_analysis)
    elif flow_kind is FlowKind.EMPLOYEE_UPSERT:
        search = _employee_search(task_analysis)
        payload = _employee_payload(task_analysis)
    elif flow_kind is FlowKind.EMPLOYEE_ADMIN:
        search = _employee_search(task_analysis)
        payload = _employee_payload(task_analysis)
    elif flow_kind is FlowKind.DEPARTMENT_UPSERT:
        search = _department_search(task_analysis)
        payload = _department_payload(task_analysis)
    elif flow_kind is FlowKind.PROJECT_UPSERT:
        search = _project_search(task_analysis)
        payload = _project_payload(task_analysis)
    elif flow_kind is FlowKind.SALES_WORKFLOW:
        search = _sales_search(task_analysis)
        payload = _sales_payload(task_analysis, combined_text=combined_text)
    elif flow_kind is FlowKind.SUPPLIER_INVOICE_WORKFLOW:
        search = _supplier_search(task_analysis)
        payload = _supplier_invoice_payload(task_analysis)
    elif flow_kind is FlowKind.INVOICE_PAYMENT_REVERSAL_WORKFLOW:
        search = _customer_search(task_analysis)
        payload = _payment_reversal_payload(task_analysis)
    elif flow_kind is FlowKind.INVOICE_CREDIT_NOTE:
        search = _customer_search(task_analysis)
        payload = _invoice_credit_note_payload(task_analysis)
    elif flow_kind is FlowKind.PROJECT_TIME_INVOICE_WORKFLOW:
        payload = _project_time_invoice_payload(task_analysis)
    elif flow_kind is FlowKind.PROJECT_LIFECYCLE_WORKFLOW:
        search = _customer_search(task_analysis)
        payload = _project_lifecycle_payload(task_analysis)
    elif flow_kind is FlowKind.INVOICE_REGISTER_PAYMENT:
        search = _invoice_payment_search(task_analysis)
        payload = _invoice_payment_payload(task_analysis)
    elif flow_kind is FlowKind.LEDGER_DIMENSION_WORKFLOW:
        payload = _ledger_dimension_payload(task_analysis)
        if payload.get("requiresVoucher") and payload.get("counterAccount") in {None, ""}:
            notes.append("Voucher creation requires a balancing counterAccount so the postings sum to zero.")
    elif flow_kind is FlowKind.OPENAPI_RESOURCE_WORKFLOW:
        search = _openapi_resource_search(task_analysis)
        payload = _openapi_resource_payload(task_analysis)

    return InternalTask(
        method_name=method_name,
        flow_kind=flow_kind,
        operation=operation,
        target_resource=target_resource,
        objective=task_analysis.objective,
        search=_drop_empty(search),
        payload=_drop_empty(payload),
        notes=tuple(notes),
    )


def _infer_flow_kind(*, task_analysis: TaskAnalysis, combined_text: str) -> FlowKind:
    family = (task_analysis.task_family or "").casefold()
    resource = _analysis_resource(task_analysis)
    operation = (task_analysis.operation or "").casefold()
    payload_keys = _analysis_field_keys(task_analysis)

    if is_invoice_payment_task(task_analysis):
        return FlowKind.INVOICE_REGISTER_PAYMENT

    if is_employee_admin_task(task_analysis, combined_text=combined_text):
        return FlowKind.EMPLOYEE_ADMIN

    if _looks_like_project_lifecycle_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.PROJECT_LIFECYCLE_WORKFLOW

    if _looks_like_payment_reversal_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.INVOICE_PAYMENT_REVERSAL_WORKFLOW

    if _looks_like_employee_onboarding_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.EMPLOYEE_ONBOARDING_WORKFLOW

    if _looks_like_travel_expense_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.TRAVEL_EXPENSE_WORKFLOW

    if _looks_like_invoice_payment_registration_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.INVOICE_REGISTER_PAYMENT

    if _looks_like_month_end_closing_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.MONTH_END_CLOSING_WORKFLOW

    if _looks_like_expense_increase_project_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.EXPENSE_INCREASE_PROJECT_WORKFLOW

    if _looks_like_salary_payroll_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.SALARY_PAYROLL_WORKFLOW

    if _looks_like_bank_reconciliation_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.BANK_RECONCILIATION_WORKFLOW

    if _looks_like_time_tracking_invoice_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.PROJECT_TIME_INVOICE_WORKFLOW

    if _looks_like_supplier_invoice_registration_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.SUPPLIER_INVOICE_WORKFLOW

    if _looks_like_invoice_credit_note_request(
        task_analysis=task_analysis,
    ):
        return FlowKind.INVOICE_CREDIT_NOTE

    if (
        resource in {"order", "invoice"}
        or "order" in family
        or any(key.startswith("orderline") for key in payload_keys)
    ):
        return FlowKind.SALES_WORKFLOW

    if resource == "employee" and (operation in {"create", "update"} or family.startswith("employee.")):
        return FlowKind.EMPLOYEE_UPSERT
    if resource == "customer" and (operation in {"create", "update"} or family.startswith("customer.")):
        return FlowKind.CUSTOMER_UPSERT
    if resource == "supplier" and (operation in {"create", "update"} or family.startswith("supplier.")):
        return FlowKind.SUPPLIER_UPSERT
    if resource == "product" and (operation in {"create", "update"} or family.startswith("product.")):
        return FlowKind.PRODUCT_UPSERT
    if resource == "department" and (operation in {"create", "update"} or family.startswith("department.")):
        return FlowKind.DEPARTMENT_UPSERT
    if resource == "project" and (operation in {"create", "update"} or family.startswith("project.")):
        return FlowKind.PROJECT_UPSERT
    if resource == "ledger" and any(
        key in payload_keys
        for key in (
            "dimensionname",
            "dimensionvalues",
            "postingdimensionvalue",
            "postingaccount",
            "counteraccount",
        )
    ):
        return FlowKind.LEDGER_DIMENSION_WORKFLOW

    return FlowKind.OPENAPI_RESOURCE_WORKFLOW


def _can_replace_with_specialized_workflow(method_name: str) -> bool:
    method_spec = METHOD_SPECS.get(method_name)
    if method_name in {
        "RunSalesWorkflow",
        "CreateEmployee",
        "UpsertEmployee",
        "CreateInvoiceCreditNote",
        "RegisterInvoicePayment",
        "RegisterSupplierInvoice",
        "RunProjectTimeInvoiceWorkflow",
        "RunTravelExpenseWorkflow",
        "RunMonthEndClosingWorkflow",
        "RunExpenseIncreaseProjectWorkflow",
    }:
        return True
    if method_spec is None:
        return True
    return method_spec.flow_kind is FlowKind.OPENAPI_RESOURCE_WORKFLOW


def _fallback_workflow_method_name(*, task_analysis: TaskAnalysis, preferred_resource: str | None = None) -> str:
    task_family_prefix = (task_analysis.task_family or "").split(".", 1)[0]
    for candidate in (preferred_resource, task_analysis.target_resource, task_family_prefix):
        canonical_family = canonical_resource_family(candidate)
        if canonical_family != "other":
            return _openapi_workflow_method_name(canonical_family)
    return _openapi_workflow_method_name("other")


def _normalize_method_name(value: Any) -> str:
    if _is_blank(value):
        return _openapi_workflow_method_name("other")
    compact = "".join(character for character in str(value) if character.isalnum()).lower()
    for method_name in METHOD_SPECS:
        if "".join(character for character in method_name if character.isalnum()).lower() == compact:
            return method_name
    return str(value)


def _expected_planner_method_name(*, task_analysis: TaskAnalysis, combined_text: str) -> str:
    flow_kind = _infer_flow_kind(task_analysis=task_analysis, combined_text=combined_text)
    operation = (task_analysis.operation or "other").lower()
    target_resource = canonical_resource_family(task_analysis.target_resource)
    return _default_supported_method_name(
        flow_kind=flow_kind,
        operation=operation,
        target_resource=target_resource,
        task_analysis=task_analysis,
    )


def _default_supported_method_name(
    *,
    flow_kind: FlowKind,
    operation: str,
    target_resource: str,
    task_analysis: TaskAnalysis,
) -> str:
    if flow_kind is FlowKind.SALES_WORKFLOW:
        return "RunSalesWorkflow"
    if flow_kind is FlowKind.PROJECT_TIME_INVOICE_WORKFLOW:
        return "RunProjectTimeInvoiceWorkflow"
    if flow_kind is FlowKind.PROJECT_LIFECYCLE_WORKFLOW:
        return "RunProjectLifecycleWorkflow"
    if flow_kind is FlowKind.SUPPLIER_INVOICE_WORKFLOW:
        return "RegisterSupplierInvoice"
    if flow_kind is FlowKind.INVOICE_CREDIT_NOTE:
        return "CreateInvoiceCreditNote"
    if flow_kind is FlowKind.INVOICE_REGISTER_PAYMENT:
        return "RegisterInvoicePayment"
    if flow_kind is FlowKind.INVOICE_PAYMENT_REVERSAL_WORKFLOW:
        return "RunInvoicePaymentReversalWorkflow"
    if flow_kind is FlowKind.EMPLOYEE_ADMIN:
        return "GrantEmployeeEntitlements"
    if flow_kind is FlowKind.LEDGER_DIMENSION_WORKFLOW:
        return "CreateLedgerDimensionWorkflow"
    if flow_kind is FlowKind.EMPLOYEE_ONBOARDING_WORKFLOW:
        return "RunEmployeeOnboardingWorkflow"
    if flow_kind is FlowKind.TRAVEL_EXPENSE_WORKFLOW:
        return "RunTravelExpenseWorkflow"
    if flow_kind is FlowKind.EXPENSE_INCREASE_PROJECT_WORKFLOW:
        return "RunExpenseIncreaseProjectWorkflow"
    if flow_kind is FlowKind.MONTH_END_CLOSING_WORKFLOW:
        return "RunMonthEndClosingWorkflow"
    if flow_kind is FlowKind.SALARY_PAYROLL_WORKFLOW:
        return "RunSalaryPayrollWorkflow"
    if flow_kind is FlowKind.BANK_RECONCILIATION_WORKFLOW:
        return "RunBankReconciliationWorkflow"
    if flow_kind is FlowKind.EMPLOYEE_UPSERT:
        return "CreateEmployee" if operation == "create" else "UpsertEmployee"
    if flow_kind is FlowKind.CUSTOMER_UPSERT:
        return "CreateCustomer" if operation == "create" else "UpsertCustomer"
    if flow_kind is FlowKind.SUPPLIER_UPSERT:
        return "CreateSupplier" if operation == "create" else "UpsertSupplier"
    if flow_kind is FlowKind.PRODUCT_UPSERT:
        return "CreateProduct" if operation == "create" else "UpsertProduct"
    if flow_kind is FlowKind.DEPARTMENT_UPSERT:
        return "CreateDepartment" if operation == "create" else "UpsertDepartment"
    if flow_kind is FlowKind.PROJECT_UPSERT:
        return "CreateProject" if operation == "create" else "UpsertProject"
    return _fallback_workflow_method_name(task_analysis=task_analysis, preferred_resource=target_resource)


def _lookup_method_argument(method_arguments: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        if key in method_arguments and not _is_blank(method_arguments[key]):
            return method_arguments[key]

    lowered = {str(key).lower(): value for key, value in method_arguments.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if not _is_blank(value):
            return value
    return None


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _analysis_field_keys(task_analysis: TaskAnalysis) -> set[str]:
    return {
        *(_normalized_key(key) for key in task_analysis.method_arguments),
        *(_normalized_key(key) for key in task_analysis.search_hints),
        *(_normalized_key(key) for key in task_analysis.payload_fields),
    }


def _analysis_search_keys(task_analysis: TaskAnalysis) -> set[str]:
    return {_normalized_key(key) for key in task_analysis.search_hints}


def _analysis_resource(task_analysis: TaskAnalysis) -> str:
    return canonical_resource_family(task_analysis.target_resource)


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped


def _is_missing_required_argument(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _should_reject_supported_method(
    *,
    method_name: str,
    task_analysis: TaskAnalysis,
    combined_text: str,
) -> bool:
    diagnostic_text = " ".join((*task_analysis.ambiguity_notes, *task_analysis.notes)).lower()
    if any(
        token in diagnostic_text
        for token in (
            "does not contain a method",
            "does not link the invoice",
            "not a true project invoicing workflow",
            "only an approximation",
            "closest supported method",
        )
    ):
        return True

    if method_name == "RunSalesWorkflow" and _looks_like_time_tracking_invoice_request(
        task_analysis=task_analysis,
    ):
        return True

    if method_name in {"CreateEmployee", "UpsertEmployee"} and _looks_like_employee_onboarding_request(
        task_analysis=task_analysis,
    ):
        return True

    if method_name in {"CreateInvoiceCreditNote", "RegisterInvoicePayment"} and _looks_like_payment_reversal_request(
        task_analysis=task_analysis,
    ):
        return True

    if method_name in {"RegisterSupplierInvoice", "RunProjectTimeInvoiceWorkflow"} and _looks_like_project_lifecycle_request(
        task_analysis=task_analysis,
    ):
        return True

    if method_name == "RunSalaryOpenAPIWorkflow" and _looks_like_salary_payroll_request(
        task_analysis=task_analysis,
    ):
        return True

    if method_name == "RunBankOpenAPIWorkflow" and _looks_like_bank_reconciliation_request(
        task_analysis=task_analysis,
    ):
        return True

    return False


def _looks_like_time_tracking_invoice_request(*, task_analysis: TaskAnalysis) -> bool:
    field_keys = _analysis_field_keys(task_analysis)
    resource = _analysis_resource(task_analysis)
    operation = (task_analysis.operation or "").casefold()
    has_time = any(key in field_keys for key in ("hours", "hourlyrate", "timesheetentries", "timeentries"))
    has_project = any(key in field_keys for key in ("projectname", "projectnumber", "activityname", "activitynumber"))
    has_invoice = operation == "invoice" or resource == "invoice"
    has_fixed_price_only = any(key in field_keys for key in ("fixedprice", "isfixedprice")) and not has_time
    return has_time and has_project and has_invoice and not has_fixed_price_only


def _looks_like_project_lifecycle_request(*, task_analysis: TaskAnalysis) -> bool:
    field_keys = _analysis_field_keys(task_analysis)
    resource = _analysis_resource(task_analysis)
    has_project = resource == "project" or any(
        key in field_keys for key in ("projectname", "projectnumber", "projectbudget")
    )
    has_time = _looks_like_time_tracking_invoice_request(
        task_analysis=task_analysis,
    ) or "timesheetentries" in field_keys
    has_supplier_cost = any(
        key in field_keys
        for key in (
            "supplierinvoice",
            "suppliername",
            "supplierorganizationnumber",
            "supplierinvoiceamountincludingvat",
        )
    )
    has_customer_invoice = (task_analysis.operation or "").casefold() == "invoice"
    return has_project and has_customer_invoice and has_time and has_supplier_cost


def _looks_like_supplier_invoice_registration_request(*, task_analysis: TaskAnalysis) -> bool:
    family = (task_analysis.task_family or "").casefold()
    resource = _analysis_resource(task_analysis)
    field_keys = _analysis_field_keys(task_analysis)
    if resource == "project" or family.startswith("project."):
        return False
    return (
        resource in {"supplierinvoice", "incominginvoice"}
        or family.startswith("supplierinvoice.")
        or family.startswith("incominginvoice.")
        or (
            any(key in field_keys for key in ("suppliername", "supplierorganizationnumber"))
            and any(
                key in field_keys
                for key in (
                    "invoicenumber",
                    "accountnumber",
                    "amountincludingvat",
                    "vatrate",
                    "invoicedate",
                    "duedate",
                )
            )
        )
    )


def _looks_like_supplier_upsert_request(*, task_analysis: TaskAnalysis) -> bool:
    if _looks_like_supplier_invoice_registration_request(task_analysis=task_analysis):
        return False
    family = (task_analysis.task_family or "").casefold()
    resource = _analysis_resource(task_analysis)
    operation = (task_analysis.operation or "").casefold()
    return resource == "supplier" or family.startswith("supplier.") or (
        operation in {"create", "update"} and any(
            key in _analysis_field_keys(task_analysis)
            for key in ("suppliername", "supplierorganizationnumber", "supplieremail")
        )
    )


def _looks_like_invoice_credit_note_request(*, task_analysis: TaskAnalysis) -> bool:
    resource = _analysis_resource(task_analysis)
    operation = (task_analysis.operation or "").casefold()
    field_keys = _analysis_field_keys(task_analysis)
    return resource == "invoice" and operation in {"reverse", "correct", "cancel"} and any(
        key in field_keys for key in ("invoicenumber", "amountexcludingvat", "description", "creditnotedate")
    )


def _looks_like_payment_reversal_request(*, task_analysis: TaskAnalysis) -> bool:
    family = (task_analysis.task_family or "").casefold()
    resource = _analysis_resource(task_analysis)
    operation = (task_analysis.operation or "").casefold()
    field_keys = _analysis_field_keys(task_analysis)
    return (
        operation == "reverse"
        and resource in {"ledger", "invoice"}
        and (
            family.endswith(".reverse")
            or any(key in field_keys for key in ("reversaldate", "amountexcludingvat", "comment"))
        )
    )


def _looks_like_employee_onboarding_request(*, task_analysis: TaskAnalysis) -> bool:
    field_keys = _analysis_field_keys(task_analysis)
    employment_markers = (
        "employmentform",
        "remunerationtype",
        "occupationcode",
        "percentageoffulltimeequivalent",
        "annualsalary",
        "hourlywage",
        "nationalidentitynumber",
        "departmentname",
        "departmentnumber",
        "startdate",
    )
    has_employee_context = _analysis_resource(task_analysis) == "employee" or (task_analysis.task_family or "").casefold().startswith(
        "employee."
    )
    return has_employee_context and (task_analysis.attachment_required or any(key in field_keys for key in employment_markers))


def _looks_like_travel_expense_request(*, task_analysis: TaskAnalysis) -> bool:
    resource = _analysis_resource(task_analysis)
    family = (task_analysis.task_family or "").casefold()
    return resource == "travelexpense" or family.startswith("travelexpense.")


def _looks_like_invoice_payment_registration_request(*, task_analysis: TaskAnalysis) -> bool:
    return is_invoice_payment_task(task_analysis) or (
        _analysis_resource(task_analysis) == "invoice" and (task_analysis.operation or "").casefold() == "register_payment"
    )


def _looks_like_expense_increase_project_request(*, task_analysis: TaskAnalysis) -> bool:
    resource = _analysis_resource(task_analysis)
    search_keys = _analysis_search_keys(task_analysis)
    field_keys = _analysis_field_keys(task_analysis)
    return resource == "project" and any(
        key in search_keys
        for key in ("datefrom", "dateto", "baselinedatefrom", "comparisondatefrom")
    ) and any(
        key in field_keys for key in ("isinternal", "createactivity", "topcount", "baselinedatefrom", "comparisondatefrom")
    )


def _looks_like_salary_payroll_request(*, task_analysis: TaskAnalysis) -> bool:
    resource = _analysis_resource(task_analysis)
    family = (task_analysis.task_family or "").casefold()
    field_keys = _analysis_field_keys(task_analysis)
    if resource != "salary" and not family.startswith("salary.") and "payroll" not in family:
        return False
    return any(
        key in field_keys
        for key in (
            "salarylines",
            "payslips",
            "basesalary",
            "bonus",
            "salarytype",
            "salarytypename",
            "salarytypenumber",
            "employeeemail",
            "month",
            "year",
            "date",
        )
    )


def _looks_like_bank_reconciliation_request(*, task_analysis: TaskAnalysis) -> bool:
    resource = _analysis_resource(task_analysis)
    family = (task_analysis.task_family or "").casefold()
    field_keys = _analysis_field_keys(task_analysis)
    if resource != "bank" and not family.startswith("bank."):
        return False
    if "reconcile" in family or "reconciliation" in family:
        return True
    return any(
        key in field_keys
        for key in (
            "statemententries",
            "statementrows",
            "bankstatemententries",
            "partialpayment",
        )
    )


def _looks_like_month_end_closing_request(*, task_analysis: TaskAnalysis) -> bool:
    resource = _analysis_resource(task_analysis)
    family = (task_analysis.task_family or "").casefold()
    field_keys = _analysis_field_keys(task_analysis)
    return (resource == "ledger" or family.startswith("ledger.")) and any(
        key in field_keys
        for key in (
            "periodizationamount",
            "prepaidaccountnumber",
            "depreciationamount",
            "depreciationaccumulatedaccountnumber",
            "payrollaccrualamount",
            "periodizationvoucher",
            "depreciationvoucher",
            "payrollaccrualvoucher",
        )
    )


def _travel_expense_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    title = lookup_analysis_value(task_analysis, "title", "purpose", "destination")
    employee_email = lookup_analysis_value(task_analysis, "employeeEmail", "email")
    first_name = lookup_analysis_value(task_analysis, "employeeFirstName", "firstName", "first_name")
    last_name = lookup_analysis_value(task_analysis, "employeeLastName", "lastName", "last_name")
    if employee_email not in {None, ""}:
        first_valid = _looks_like_person_name_component(first_name)
        last_valid = _looks_like_person_name_component(last_name, allow_multiple=True)
        if not (first_valid and last_valid):
            first_name = None
            last_name = None
    departure_date = lookup_analysis_value(task_analysis, "departureDate")
    return_date = lookup_analysis_value(task_analysis, "returnDate")
    duration_days = _coerce_number(lookup_analysis_value(task_analysis, "durationDays", "perDiemCount"))
    if duration_days is None and departure_date and return_date:
        duration_days = _inclusive_iso_date_span(str(departure_date), str(return_date))
    destination = lookup_analysis_value(task_analysis, "destination", "location") or title
    per_diem_rate = _coerce_number(lookup_analysis_value(task_analysis, "perDiemRate"))
    expenses = _normalized_travel_expense_entries(
        lookup_analysis_value(task_analysis, "expenses", "costs"),
        default_date=str(departure_date) if departure_date not in {None, ""} else None,
    )
    return _drop_empty(
        {
            "title": title,
            "employeeEmail": employee_email,
            "employeeFirstName": first_name,
            "employeeLastName": last_name,
            "departureDate": departure_date,
            "returnDate": return_date,
            "durationDays": duration_days,
            "destination": destination,
            "perDiemRate": per_diem_rate,
            "perDiemCount": duration_days,
            "expenses": expenses,
        }
    )


def _month_end_closing_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    voucher_date = lookup_analysis_value(task_analysis, "voucherDate", "date")
    period_label = lookup_analysis_value(task_analysis, "periodLabel")
    verify_trial_balance = lookup_analysis_value(task_analysis, "verifyTrialBalance")

    return _drop_empty(
        {
            "voucherDate": voucher_date,
            "periodLabel": period_label,
            "verifyTrialBalance": bool(verify_trial_balance) if verify_trial_balance is not None else None,
            "periodizationAmount": _coerce_number(lookup_analysis_value(task_analysis, "periodizationAmount")),
            "prepaidAccountNumber": lookup_analysis_value(task_analysis, "prepaidAccountNumber"),
            "periodizationExpenseAccountNumber": lookup_analysis_value(task_analysis, "periodizationExpenseAccountNumber"),
            "depreciationAmount": _coerce_number(lookup_analysis_value(task_analysis, "depreciationAmount")),
            "depreciationExpenseAccountNumber": lookup_analysis_value(task_analysis, "depreciationExpenseAccountNumber"),
            "depreciationAccumulatedAccountNumber": lookup_analysis_value(task_analysis, "depreciationAccumulatedAccountNumber"),
            "payrollAccrualAmount": _coerce_number(lookup_analysis_value(task_analysis, "payrollAccrualAmount")),
            "payrollExpenseAccountNumber": lookup_analysis_value(task_analysis, "payrollExpenseAccountNumber"),
            "payrollLiabilityAccountNumber": lookup_analysis_value(task_analysis, "payrollLiabilityAccountNumber"),
        }
    )


def _invoice_payment_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number"),
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name", "name"),
            "customerOrganizationNumber": lookup_analysis_value(
                task_analysis,
                "customerOrganizationNumber",
                "organizationNumber",
            ),
            "paidAmount": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "paidAmount",
                    "paymentAmount",
                    "amount",
                    "amountCurrency",
                )
            ),
            "currencyCode": lookup_analysis_value(task_analysis, "currencyCode", "invoiceCurrency", "currency"),
            "paymentDate": default_action_date(task_analysis, "paymentDate", "date"),
            "invoiceAmount": _coerce_number(lookup_analysis_value(task_analysis, "invoiceAmount", "amount")),
            "invoiceDateFrom": lookup_analysis_value(task_analysis, "invoiceDateFrom", "dateFrom", "date_from"),
            "invoiceDateTo": lookup_analysis_value(task_analysis, "invoiceDateTo", "dateTo", "date_to"),
        }
    )


def _expense_increase_project_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    derived_periods = _derive_comparison_month_arguments(task_analysis)
    return _drop_empty(
        {
            "baselineDateFrom": lookup_analysis_value(task_analysis, "baselineDateFrom") or derived_periods.get("baselineDateFrom"),
            "baselineDateTo": lookup_analysis_value(task_analysis, "baselineDateTo") or derived_periods.get("baselineDateTo"),
            "comparisonDateFrom": lookup_analysis_value(task_analysis, "comparisonDateFrom") or derived_periods.get("comparisonDateFrom"),
            "comparisonDateTo": lookup_analysis_value(task_analysis, "comparisonDateTo") or derived_periods.get("comparisonDateTo"),
            "baselineLabel": lookup_analysis_value(task_analysis, "baselineLabel"),
            "comparisonLabel": lookup_analysis_value(task_analysis, "comparisonLabel"),
            "topCount": int(_coerce_number(lookup_analysis_value(task_analysis, "topCount")) or 3),
            "isInternal": lookup_analysis_value(task_analysis, "isInternal"),
            "createActivity": lookup_analysis_value(task_analysis, "createActivity"),
        }
    )


def _salary_payroll_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    employee = _drop_empty(
        {
            "email": lookup_analysis_value(task_analysis, "employeeEmail", "email"),
            "firstName": lookup_analysis_value(task_analysis, "employeeFirstName", "firstName"),
            "lastName": lookup_analysis_value(task_analysis, "employeeLastName", "lastName"),
        }
    )
    payslips = lookup_analysis_value(task_analysis, "payslips")
    if isinstance(payslips, list) and payslips:
        first_payslip = payslips[0] if isinstance(payslips[0], dict) else {}
        payslip_employee = first_payslip.get("employee") if isinstance(first_payslip, dict) else {}
        if isinstance(payslip_employee, dict):
            employee = _drop_empty(
                {
                    "email": employee.get("email") or payslip_employee.get("email"),
                    "firstName": employee.get("firstName") or payslip_employee.get("firstName"),
                    "lastName": employee.get("lastName") or payslip_employee.get("lastName"),
                }
            )

    return _drop_empty(
        {
            "employeeEmail": employee.get("email"),
            "employeeFirstName": employee.get("firstName"),
            "employeeLastName": employee.get("lastName"),
            "date": lookup_analysis_value(task_analysis, "date"),
            "month": _coerce_number(lookup_analysis_value(task_analysis, "month")),
            "year": _coerce_number(lookup_analysis_value(task_analysis, "year")),
            "paySlipsAvailableDate": lookup_analysis_value(task_analysis, "paySlipsAvailableDate"),
            "isHistorical": lookup_analysis_value(task_analysis, "isHistorical"),
            "generateTaxDeduction": lookup_analysis_value(task_analysis, "generateTaxDeduction"),
            "salaryLines": _salary_payroll_lines(task_analysis),
            "payslips": payslips if isinstance(payslips, list) else None,
        }
    )


def _salary_payroll_lines(task_analysis: TaskAnalysis) -> list[dict[str, Any]]:
    raw_lines = lookup_analysis_value(task_analysis, "salaryLines")
    normalized = _normalize_salary_lines(raw_lines)
    if normalized:
        return normalized

    payslips = lookup_analysis_value(task_analysis, "payslips")
    if not isinstance(payslips, list):
        return []
    extracted: list[dict[str, Any]] = []
    for payslip in payslips:
        if not isinstance(payslip, dict):
            continue
        for specification in payslip.get("specifications") or []:
            if not isinstance(specification, dict):
                continue
            salary_type = specification.get("salaryType") if isinstance(specification.get("salaryType"), dict) else {}
            extracted.append(
                _drop_empty(
                    {
                        "salaryTypeName": salary_type.get("name"),
                        "salaryTypeNumber": salary_type.get("number"),
                        "amount": _coerce_number(specification.get("amount")),
                        "rate": _coerce_number(specification.get("rate")),
                        "count": _coerce_number(specification.get("count")),
                        "description": specification.get("description"),
                    }
                )
            )
    return [entry for entry in extracted if entry]


def _normalize_salary_lines(raw_value: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        salary_type = item.get("salaryType") if isinstance(item.get("salaryType"), dict) else {}
        normalized.append(
            _drop_empty(
                {
                    "salaryTypeName": item.get("salaryTypeName") or item.get("typeName") or salary_type.get("name"),
                    "salaryTypeNumber": item.get("salaryTypeNumber") or item.get("typeNumber") or salary_type.get("number"),
                    "amount": _coerce_number(item.get("amount")),
                    "rate": _coerce_number(item.get("rate")),
                    "count": _coerce_number(item.get("count")),
                    "description": item.get("description"),
                }
            )
        )
    return [entry for entry in normalized if entry]


def _bank_reconciliation_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    entries = _bank_statement_entries(task_analysis)
    date_from, date_to = _bank_statement_date_window(entries)
    return _drop_empty(
        {
            "statementEntries": entries,
            "fromDate": lookup_analysis_value(task_analysis, "fromDate", "dateFrom") or date_from,
            "toDate": lookup_analysis_value(task_analysis, "toDate", "dateTo") or date_to,
            "bankAccountNumber": lookup_analysis_value(task_analysis, "bankAccountNumber", "accountNumber"),
            "bankRegisterNumber": lookup_analysis_value(task_analysis, "bankRegisterNumber", "registerNumber"),
            "bankName": lookup_analysis_value(task_analysis, "bankName"),
        }
    )


def _bank_statement_entries(task_analysis: TaskAnalysis) -> list[dict[str, Any]]:
    raw_entries = lookup_analysis_value(task_analysis, "statementEntries", "statementRows", "bankStatementEntries")
    if not isinstance(raw_entries, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_entries, start=1):
        if not isinstance(item, dict):
            continue
        customer = item.get("customer") if isinstance(item.get("customer"), dict) else {}
        supplier = item.get("supplier") if isinstance(item.get("supplier"), dict) else {}
        amount = _coerce_number(
            item.get("amount")
            or item.get("amountCurrency")
            or item.get("paidAmount")
            or item.get("paymentAmount")
        )
        normalized.append(
            _drop_empty(
                {
                    "entryId": item.get("entryId") or item.get("referenceId") or f"entry-{index}",
                    "paymentDate": item.get("paymentDate") or item.get("date"),
                    "direction": item.get("direction"),
                    "amount": amount,
                    "currencyCode": item.get("currencyCode") or item.get("currency"),
                    "invoiceNumber": item.get("invoiceNumber"),
                    "description": item.get("description") or item.get("text"),
                    "partialPayment": item.get("partialPayment"),
                    "invoiceDateFrom": item.get("invoiceDateFrom"),
                    "invoiceDateTo": item.get("invoiceDateTo"),
                    "customer": _drop_empty(
                        {
                            "customerName": item.get("customerName") or customer.get("name"),
                            "organizationNumber": item.get("customerOrganizationNumber") or customer.get("organizationNumber"),
                            "email": item.get("customerEmail") or customer.get("email"),
                        }
                    ),
                    "supplier": _drop_empty(
                        {
                            "supplierName": item.get("supplierName") or supplier.get("name"),
                            "organizationNumber": item.get("supplierOrganizationNumber") or supplier.get("organizationNumber"),
                            "email": item.get("supplierEmail") or supplier.get("email"),
                        }
                    ),
                }
            )
        )
    return [entry for entry in normalized if entry]


def _bank_statement_date_window(entries: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    dates = sorted(
        {
            str(entry.get("paymentDate"))
            for entry in entries
            if entry.get("paymentDate") not in {None, ""}
        }
    )
    if not dates:
        return None, None
    return dates[0], dates[-1]


def _looks_like_person_name_component(value: Any, *, allow_multiple: bool = False) -> bool:
    if value in {None, ""}:
        return False
    words = str(value).strip().split()
    if not words:
        return False
    if not allow_multiple and len(words) != 1:
        return False
    if allow_multiple and len(words) > 4:
        return False
    for word in words:
        if not re.fullmatch(r"[A-Za-zÆØÅÄÖÜÉÈÀÇ][A-Za-zÆØÅÄÖÜÉÈÀÇ' -]{0,39}", word):
            return False
    return True


def _normalized_travel_expense_entries(raw_value: Any, *, default_date: str | None) -> list[dict[str, Any]]:
    if not isinstance(raw_value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        normalized_entry = _drop_empty(
            {
                "description": item.get("description") or item.get("comments"),
                "amount": _coerce_number(item.get("amount") or item.get("amountCurrencyIncVat")),
                "date": item.get("date") or default_date,
            }
        )
        if normalized_entry:
            normalized.append(normalized_entry)
    return normalized


def _project_time_invoice_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    employee_email = lookup_analysis_value(task_analysis, "employeeEmail", "employee_email", "email")
    first_name = lookup_analysis_value(task_analysis, "employeeFirstName", "firstName", "first_name")
    last_name = lookup_analysis_value(task_analysis, "employeeLastName", "lastName", "last_name")
    if (first_name in {None, ""} or last_name in {None, ""}) and employee_email in {None, ""}:
        full_name = lookup_analysis_value(task_analysis, "employeeName", "name", "displayName")
        if full_name not in {None, ""}:
            parts = str(full_name).strip().split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])

    return _drop_empty(
        {
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name"),
            "customerOrganizationNumber": lookup_analysis_value(
                task_analysis,
                "customerOrganizationNumber",
                "customer_organizationNumber",
                "organizationNumber",
            ),
            "employeeEmail": employee_email,
            "employeeFirstName": first_name,
            "employeeLastName": last_name,
            "projectName": lookup_analysis_value(task_analysis, "projectName", "project_name"),
            "projectNumber": lookup_analysis_value(task_analysis, "projectNumber"),
            "activityName": lookup_analysis_value(task_analysis, "activityName", "activity_name"),
            "activityNumber": lookup_analysis_value(task_analysis, "activityNumber"),
            "hours": _coerce_number(lookup_analysis_value(task_analysis, "hours")),
            "hourlyRate": _coerce_number(lookup_analysis_value(task_analysis, "hourlyRate", "hourly_rate")),
            "date": default_action_date(task_analysis, "date"),
            "comment": lookup_analysis_value(task_analysis, "comment"),
            "invoiceDate": default_action_date(task_analysis, "invoiceDate", "date"),
            "orderDate": default_action_date(task_analysis, "orderDate", "date"),
        }
    )


def _employee_onboarding_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    employee_payload = _employee_payload(task_analysis)
    employment = dict(employee_payload.pop("employment", {}) or {})
    department_ref = dict(employee_payload.pop("departmentRef", {}) or {})
    return _drop_empty(
        {
            **employee_payload,
            "departmentName": department_ref.get("name"),
            "departmentNumber": department_ref.get("departmentNumber"),
            "startDate": employment.get("startDate"),
            "employmentForm": employment.get("employmentForm"),
            "remunerationType": employment.get("remunerationType"),
            "occupationCode": (employment.get("occupationCodeRef") or {}).get("code")
            or (employment.get("occupationCodeRef") or {}).get("nameNO"),
            "percentageOfFullTimeEquivalent": employment.get("percentageOfFullTimeEquivalent"),
            "annualSalary": employment.get("annualSalary"),
            "hourlyWage": employment.get("hourlyWage"),
        }
    )


def _payment_reversal_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name", "name"),
            "customerOrganizationNumber": lookup_analysis_value(
                task_analysis,
                "customerOrganizationNumber",
                "customer_organizationNumber",
                "organizationNumber",
            ),
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number"),
            "description": lookup_analysis_value(
                task_analysis,
                "description",
                "invoiceDescription",
                "lineDescription",
            ),
            "amountExcludingVat": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "amountExcludingVat",
                    "amountExcludingVatCurrency",
                    "amount",
                )
            ),
            "reversalDate": default_action_date(task_analysis, "reversalDate", "paymentDate", "date"),
            "comment": lookup_analysis_value(task_analysis, "comment"),
        }
    )


def _project_lifecycle_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    supplier_invoice = _raw_supplier_invoice_fields(task_analysis)
    return _drop_empty(
        {
            "projectName": lookup_analysis_value(task_analysis, "projectName", "project_name", "name"),
            "projectNumber": lookup_analysis_value(task_analysis, "projectNumber", "number"),
            "projectBudget": _coerce_number(
                lookup_analysis_value(task_analysis, "projectBudget", "budget", "budgetAmount", "fixedprice", "fixedPrice")
            ),
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name"),
            "customerOrganizationNumber": lookup_analysis_value(
                task_analysis,
                "customerOrganizationNumber",
                "customer_organizationNumber",
                "organizationNumber",
            ),
            "projectManagerEmail": lookup_analysis_value(task_analysis, "projectManagerEmail"),
            "projectManagerFirstName": lookup_analysis_value(task_analysis, "projectManagerFirstName"),
            "projectManagerLastName": lookup_analysis_value(task_analysis, "projectManagerLastName"),
            "activityName": lookup_analysis_value(task_analysis, "activityName", "activity_name"),
            "timesheetEntries": _extract_lifecycle_timesheet_entries(task_analysis),
            "supplierName": supplier_invoice.get("supplierName"),
            "supplierOrganizationNumber": supplier_invoice.get("supplierOrganizationNumber"),
            "supplierInvoiceNumber": supplier_invoice.get("invoiceNumber"),
            "supplierInvoiceDescription": supplier_invoice.get("description"),
            "supplierInvoiceAmountIncludingVat": supplier_invoice.get("amountIncludingVat"),
            "supplierAccountNumber": supplier_invoice.get("accountNumber"),
            "vatRate": supplier_invoice.get("vatRate"),
            "invoiceDate": default_action_date(task_analysis, "invoiceDate", "date"),
            "invoiceDueDate": default_action_date(task_analysis, "invoiceDueDate", "paymentDate", "invoiceDate", "date"),
        }
    )


def _supplier_invoice_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "supplierName": lookup_analysis_value(task_analysis, "supplierName", "name"),
            "supplierOrganizationNumber": lookup_analysis_value(
                task_analysis,
                "supplierOrganizationNumber",
                "organizationNumber",
            ),
            "supplierEmail": lookup_analysis_value(task_analysis, "supplierEmail", "email"),
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number", "externalId"),
            "description": lookup_analysis_value(
                task_analysis,
                "description",
                "invoiceDescription",
                "lineDescription",
            ),
            "accountNumber": lookup_analysis_value(
                task_analysis,
                "accountNumber",
                "ledgerAccountNumber",
                "postingAccount",
                "account",
            ),
            "amountIncludingVat": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "amountIncludingVat",
                    "amountInclVat",
                    "invoiceAmount",
                    "amountCurrency",
                    "amount",
                )
            ),
            "vatRate": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "vatRate",
                    "vatPercentage",
                    "percentage",
                    "rate",
                )
            ),
            "invoiceDate": default_action_date(task_analysis, "invoiceDate", "date"),
            "dueDate": default_action_date(task_analysis, "dueDate", "paymentDate", "invoiceDate", "date"),
            "voucherTypeName": lookup_analysis_value(task_analysis, "voucherTypeName", "voucherType"),
        }
    )


def _invoice_credit_note_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name", "name"),
            "customerOrganizationNumber": lookup_analysis_value(
                task_analysis,
                "customerOrganizationNumber",
                "customer_organizationNumber",
                "organizationNumber",
            ),
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number"),
            "description": lookup_analysis_value(
                task_analysis,
                "description",
                "invoiceDescription",
                "lineDescription",
                "orderLineDescription",
            ),
            "amountExcludingVat": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "amountExcludingVat",
                    "amountExcludingVatCurrency",
                    "amount",
                )
            ),
            "creditNoteDate": default_action_date(task_analysis, "creditNoteDate", "date"),
            "comment": lookup_analysis_value(task_analysis, "comment", "creditNoteComment"),
        }
    )


def _customer_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "organizationNumber": lookup_analysis_value(
                task_analysis,
                "organizationNumber",
                "customer_organizationNumber",
                "customerOrganizationNumber",
            ),
            "email": lookup_analysis_value(task_analysis, "customerEmail", "invoiceEmail", "email"),
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name", "name"),
            "count": 10,
        }
    )


def _customer_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "name": lookup_analysis_value(task_analysis, "customerName", "customer_name", "name"),
            "organizationNumber": lookup_analysis_value(
                task_analysis,
                "organizationNumber",
                "customer_organizationNumber",
                "customerOrganizationNumber",
            ),
            "email": lookup_analysis_value(task_analysis, "customerEmail", "email"),
            "invoiceEmail": lookup_analysis_value(task_analysis, "invoiceEmail"),
            "phoneNumber": lookup_analysis_value(task_analysis, "phoneNumber", "phone"),
            "phoneNumberMobile": lookup_analysis_value(task_analysis, "phoneNumberMobile", "mobile"),
            "description": lookup_analysis_value(task_analysis, "description"),
        }
    )


def _supplier_method_arguments(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "name": lookup_analysis_value(task_analysis, "supplierName", "name"),
            "organizationNumber": lookup_analysis_value(
                task_analysis,
                "supplierOrganizationNumber",
                "organizationNumber",
            ),
            "email": lookup_analysis_value(task_analysis, "supplierEmail", "email"),
            "invoiceEmail": lookup_analysis_value(task_analysis, "invoiceEmail"),
            "phoneNumber": lookup_analysis_value(task_analysis, "phoneNumber", "phone"),
            "phoneNumberMobile": lookup_analysis_value(task_analysis, "phoneNumberMobile", "mobile"),
            "description": lookup_analysis_value(task_analysis, "description"),
        }
    )


def _product_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "productNumber": lookup_analysis_value(task_analysis, "productNumber", "number"),
            "name": lookup_analysis_value(task_analysis, "productName", "name"),
            "count": 10,
        }
    )


def _product_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "name": lookup_analysis_value(task_analysis, "productName", "name", "description"),
            "number": lookup_analysis_value(task_analysis, "productNumber", "number"),
            "description": lookup_analysis_value(task_analysis, "description"),
            "orderLineDescription": lookup_analysis_value(task_analysis, "orderLineDescription"),
            "priceExcludingVatCurrency": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "priceExcludingVatCurrency",
                    "priceExcludingVat",
                    "unitPrice",
                    "unit_price",
                    "amount",
                )
            ),
        }
    )


def _employee_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "email": lookup_analysis_value(task_analysis, "email"),
            "employeeNumber": lookup_analysis_value(task_analysis, "employeeNumber"),
            "firstName": lookup_analysis_value(task_analysis, "firstName", "first_name"),
            "lastName": lookup_analysis_value(task_analysis, "lastName", "last_name"),
            "count": 10,
        }
    )


def _employee_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    first_name = lookup_analysis_value(task_analysis, "firstName", "first_name")
    last_name = lookup_analysis_value(task_analysis, "lastName", "last_name")

    if first_name in {None, ""} or last_name in {None, ""}:
        full_name = lookup_analysis_value(task_analysis, "name", "fullName", "displayName")
        if full_name not in {None, ""}:
            parts = str(full_name).strip().split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])

    payload = _drop_empty(
        {
            "firstName": first_name,
            "lastName": last_name,
            "email": lookup_analysis_value(task_analysis, "email"),
            "employeeNumber": lookup_analysis_value(task_analysis, "employeeNumber"),
            "dateOfBirth": lookup_analysis_value(task_analysis, "dateOfBirth", "birthDate"),
            "nationalIdentityNumber": lookup_analysis_value(
                task_analysis,
                "nationalIdentityNumber",
                "national_identity_number",
                "socialSecurityNumber",
            ),
            "bankAccountNumber": lookup_analysis_value(task_analysis, "bankAccountNumber", "accountNumber"),
            "phoneNumberMobile": lookup_analysis_value(task_analysis, "phoneNumberMobile", "mobile"),
            "phoneNumberWork": lookup_analysis_value(task_analysis, "phoneNumber", "phone"),
            "comments": lookup_analysis_value(task_analysis, "comments", "comment"),
        }
    )

    user_type = lookup_analysis_value(task_analysis, "userType")
    if user_type not in {None, ""}:
        payload["userType"] = user_type
    template = lookup_analysis_value(task_analysis, "template")
    if template not in {None, ""}:
        payload["template"] = template

    department_ref = _drop_empty(
        {
            "departmentNumber": lookup_analysis_value(task_analysis, "departmentNumber"),
            "name": lookup_analysis_value(task_analysis, "departmentName"),
        }
    )
    if department_ref:
        payload["departmentRef"] = department_ref

    employment = _drop_empty(
        {
            "startDate": lookup_analysis_value(task_analysis, "startDate"),
            "employmentForm": _normalize_employment_form(
                lookup_analysis_value(task_analysis, "employmentForm")
            ),
            "remunerationType": _normalize_remuneration_type(
                lookup_analysis_value(task_analysis, "remunerationType")
            ),
            "percentageOfFullTimeEquivalent": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "percentageOfFullTimeEquivalent",
                    "employmentPercentage",
                    "percentage",
                )
            ),
            "annualSalary": _coerce_number(
                lookup_analysis_value(task_analysis, "annualSalary", "salary", "salaryAmount")
            ),
            "hourlyWage": _coerce_number(
                lookup_analysis_value(task_analysis, "hourlyWage", "hourlyRate", "hourlySalary")
            ),
        }
    )
    occupation_code_ref = _employee_occupation_code_ref(task_analysis)
    if occupation_code_ref:
        employment["occupationCodeRef"] = occupation_code_ref
    if employment:
        payload["employment"] = employment
    return payload


def _employee_onboarding_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _employee_payload(task_analysis)


def _travel_expense_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "email": lookup_analysis_value(task_analysis, "employeeEmail", "email"),
            "firstName": lookup_analysis_value(task_analysis, "employeeFirstName", "firstName"),
            "lastName": lookup_analysis_value(task_analysis, "employeeLastName", "lastName"),
            "employeeNumber": lookup_analysis_value(task_analysis, "employeeNumber"),
            "count": 10,
        }
    )


def _travel_expense_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    departure_date = lookup_analysis_value(task_analysis, "departureDate")
    return_date = lookup_analysis_value(task_analysis, "returnDate")
    title = lookup_analysis_value(task_analysis, "title", "purpose", "destination")
    destination = lookup_analysis_value(task_analysis, "destination", "location") or title
    duration_days = _coerce_number(lookup_analysis_value(task_analysis, "durationDays", "perDiemCount"))
    per_diem_rate = _coerce_number(lookup_analysis_value(task_analysis, "perDiemRate"))
    expenses = lookup_analysis_value(task_analysis, "expenses")
    normalized_expenses: list[dict[str, Any]] = []
    if isinstance(expenses, list):
        for item in expenses:
            if not isinstance(item, dict):
                continue
            normalized_expenses.append(
                _drop_empty(
                    {
                        "description": item.get("description") or item.get("comments"),
                        "amount": _coerce_number(item.get("amount") or item.get("amountCurrencyIncVat")),
                        "date": item.get("date") or departure_date,
                    }
                )
            )
    per_diem_count = _coerce_number(lookup_analysis_value(task_analysis, "perDiemCount")) or duration_days
    payload = _drop_empty(
        {
            "title": title,
            "travelDetails": _drop_empty(
                {
                    "departureDate": departure_date,
                    "returnDate": return_date,
                    "destination": destination,
                    "purpose": title,
                    "isDayTrip": bool(duration_days == 1) if duration_days is not None else None,
                }
            ),
            "perDiemCompensations": [
                _drop_empty(
                    {
                        "count": int(per_diem_count) if per_diem_count is not None else None,
                        "rate": per_diem_rate,
                        "amount": round(per_diem_count * per_diem_rate, 2)
                        if per_diem_count is not None and per_diem_rate is not None
                        else None,
                        "location": destination,
                    }
                )
            ]
            if per_diem_rate is not None
            else [],
            "costs": normalized_expenses,
        }
    )
    return payload


def _month_end_closing_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    voucher_date = lookup_analysis_value(task_analysis, "voucherDate")
    period_label = lookup_analysis_value(task_analysis, "periodLabel") or voucher_date
    vouchers: list[dict[str, Any]] = []

    periodization_amount = _coerce_number(lookup_analysis_value(task_analysis, "periodizationAmount"))
    prepaid_account = lookup_analysis_value(task_analysis, "prepaidAccountNumber")
    periodization_expense = lookup_analysis_value(task_analysis, "periodizationExpenseAccountNumber")
    if periodization_amount is not None and prepaid_account not in {None, ""} and periodization_expense not in {None, ""}:
        vouchers.append(
            {
                "key": "periodization",
                "description": f"Month-end {period_label} - prepaid cost periodization",
                "postings": [
                    {"accountNumber": str(periodization_expense), "amount": round(periodization_amount, 2)},
                    {"accountNumber": str(prepaid_account), "amount": round(-periodization_amount, 2)},
                ],
            }
        )

    depreciation_amount = _coerce_number(lookup_analysis_value(task_analysis, "depreciationAmount"))
    depreciation_expense = lookup_analysis_value(task_analysis, "depreciationExpenseAccountNumber")
    depreciation_accumulated = lookup_analysis_value(task_analysis, "depreciationAccumulatedAccountNumber")
    if (
        depreciation_amount is not None
        and depreciation_expense not in {None, ""}
        and depreciation_accumulated not in {None, ""}
    ):
        vouchers.append(
            {
                "key": "depreciation",
                "description": f"Month-end {period_label} - depreciation",
                "postings": [
                    {"accountNumber": str(depreciation_expense), "amount": round(depreciation_amount, 2)},
                    {"accountNumber": str(depreciation_accumulated), "amount": round(-depreciation_amount, 2)},
                ],
            }
        )

    payroll_amount = _coerce_number(lookup_analysis_value(task_analysis, "payrollAccrualAmount"))
    payroll_expense = lookup_analysis_value(task_analysis, "payrollExpenseAccountNumber")
    payroll_liability = lookup_analysis_value(task_analysis, "payrollLiabilityAccountNumber")
    if payroll_amount is not None and payroll_expense not in {None, ""} and payroll_liability not in {None, ""}:
        vouchers.append(
            {
                "key": "payroll_accrual",
                "description": f"Month-end {period_label} - payroll accrual",
                "postings": [
                    {"accountNumber": str(payroll_expense), "amount": round(payroll_amount, 2)},
                    {"accountNumber": str(payroll_liability), "amount": round(-payroll_amount, 2)},
                ],
            }
        )

    return _drop_empty(
        {
            "voucherDate": voucher_date,
            "periodLabel": period_label,
            "verifyTrialBalance": lookup_analysis_value(task_analysis, "verifyTrialBalance"),
            "vouchers": vouchers,
        }
    )


def _normalize_employment_form(value: Any) -> str | None:
    if _is_blank(value):
        return None
    text = " ".join(str(value).strip().upper().replace("-", " ").split())
    if text in {
        "PERMANENT",
        "TEMPORARY",
        "PERMANENT_AND_HIRED_OUT",
        "TEMPORARY_AND_HIRED_OUT",
        "TEMPORARY_ON_CALL",
        "NOT_CHOSEN",
    }:
        return text
    lowered = text.lower()
    if "tilkall" in lowered or "on call" in lowered:
        return "TEMPORARY_ON_CALL"
    if "midlertidig" in lowered or "temporary" in lowered:
        if "utleid" in lowered or "hired out" in lowered:
            return "TEMPORARY_AND_HIRED_OUT"
        return "TEMPORARY"
    if "fast" in lowered or "permanent" in lowered:
        if "utleid" in lowered or "hired out" in lowered:
            return "PERMANENT_AND_HIRED_OUT"
        return "PERMANENT"
    return None


def _normalize_remuneration_type(value: Any) -> str | None:
    if _is_blank(value):
        return None
    text = " ".join(str(value).strip().upper().replace("-", " ").split())
    if text in {
        "MONTHLY_WAGE",
        "HOURLY_WAGE",
        "COMMISION_PERCENTAGE",
        "FEE",
        "NOT_CHOSEN",
        "PIECEWORK_WAGE",
    }:
        return text
    lowered = text.lower()
    if any(token in lowered for token in ("måned", "maaned", "monthly", "fastlønn", "fastlonn")):
        return "MONTHLY_WAGE"
    if any(token in lowered for token in ("time", "hour", "timelønn", "timelonn")):
        return "HOURLY_WAGE"
    if "provis" in lowered or "commission" in lowered:
        return "COMMISION_PERCENTAGE"
    if "honorar" in lowered or "fee" in lowered:
        return "FEE"
    if "akkord" in lowered or "piecework" in lowered:
        return "PIECEWORK_WAGE"
    return None


def _employee_occupation_code_ref(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    value = lookup_analysis_value(
        task_analysis,
        "occupationCode",
        "occupationCodeCode",
        "occupation_code",
    )
    if _is_blank(value):
        return None
    if isinstance(value, dict):
        return _drop_empty(
            {
                "id": value.get("id"),
                "code": value.get("code"),
                "nameNO": value.get("nameNO"),
            }
        )
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return {"code": text}
    return {"nameNO": text}


def _department_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "departmentNumber": lookup_analysis_value(task_analysis, "departmentNumber"),
            "name": lookup_analysis_value(task_analysis, "departmentName", "name"),
            "count": 10,
        }
    )


def _department_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "name": lookup_analysis_value(task_analysis, "departmentName", "name"),
            "departmentNumber": lookup_analysis_value(task_analysis, "departmentNumber"),
        }
    )


def _project_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "number": lookup_analysis_value(task_analysis, "projectNumber", "number"),
            "name": lookup_analysis_value(task_analysis, "projectName", "name"),
            "count": 10,
        }
    )


def _project_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    payload = _drop_empty(
        {
            "name": lookup_analysis_value(task_analysis, "projectName", "name"),
            "number": lookup_analysis_value(task_analysis, "projectNumber", "number"),
            "description": lookup_analysis_value(task_analysis, "description"),
            "reference": lookup_analysis_value(task_analysis, "reference"),
            "startDate": lookup_analysis_value(task_analysis, "startDate"),
            "endDate": lookup_analysis_value(task_analysis, "endDate"),
            "invoiceReceiverEmail": lookup_analysis_value(task_analysis, "invoiceReceiverEmail"),
            "overdueNoticeEmail": lookup_analysis_value(task_analysis, "overdueNoticeEmail"),
            "isFixedPrice": lookup_analysis_value(task_analysis, "isFixedPrice"),
            "fixedprice": _coerce_number(
                lookup_analysis_value(task_analysis, "fixedprice", "fixedPrice")
            ),
        }
    )

    customer_ref = _drop_empty(
        {
            "organizationNumber": lookup_analysis_value(
                task_analysis,
                "customer_organizationNumber",
                "customerOrganizationNumber",
                "organizationNumber",
            ),
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name"),
        }
    )
    if customer_ref:
        payload["customerRef"] = customer_ref

    department_ref = _drop_empty(
        {
            "departmentNumber": lookup_analysis_value(task_analysis, "departmentNumber"),
            "name": lookup_analysis_value(task_analysis, "departmentName"),
        }
    )
    if department_ref:
        payload["departmentRef"] = department_ref

    manager_ref = _drop_empty(
        {
            "email": lookup_analysis_value(task_analysis, "projectManagerEmail", "email"),
            "firstName": lookup_analysis_value(task_analysis, "projectManagerFirstName", "firstName"),
            "lastName": lookup_analysis_value(task_analysis, "projectManagerLastName", "lastName"),
        }
    )
    if manager_ref:
        payload["projectManagerRef"] = manager_ref

    return payload


def _openapi_resource_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    search = dict(task_analysis.search_hints or {})
    for key in (
        "id",
        "name",
        "number",
        "email",
        "organizationNumber",
        "invoiceNumber",
        "customerId",
        "supplierId",
        "employeeId",
        "departmentId",
        "projectId",
        "activityId",
        "date",
        "dateFrom",
        "dateTo",
        "departureDateFrom",
        "returnDateTo",
        "code",
        "query",
    ):
        value = lookup_analysis_value(task_analysis, key)
        if value not in {None, ""}:
            search.setdefault(key, value)
    if search and "count" not in search:
        search["count"] = 10
    return _drop_empty(search)


def _openapi_resource_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    payload = dict(task_analysis.payload_fields or {})
    search_keys = {_normalized_key(key) for key in task_analysis.search_hints}
    for key, value in (task_analysis.method_arguments or {}).items():
        normalized = _normalized_key(key)
        if normalized in search_keys or normalized in {"from", "count", "fields", "sorting"}:
            continue
        payload.setdefault(key, value)
    if lookup_analysis_value(task_analysis, "moduleDepartmentAccounting", "enableDepartmentAccounting") is True:
        payload.setdefault("moduleDepartmentAccounting", True)
    return _drop_empty(payload)


def _sales_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _customer_search(task_analysis)


def _supplier_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "organizationNumber": lookup_analysis_value(
                task_analysis,
                "supplierOrganizationNumber",
                "organizationNumber",
            ),
            "email": lookup_analysis_value(task_analysis, "supplierEmail", "email"),
            "invoiceEmail": lookup_analysis_value(task_analysis, "invoiceEmail"),
            "count": 10,
            "fields": "id,name,organizationNumber,email,invoiceEmail",
        }
    )


def _supplier_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "name": lookup_analysis_value(task_analysis, "supplierName", "name"),
            "organizationNumber": lookup_analysis_value(
                task_analysis,
                "supplierOrganizationNumber",
                "organizationNumber",
            ),
            "email": lookup_analysis_value(task_analysis, "supplierEmail", "email"),
            "invoiceEmail": lookup_analysis_value(task_analysis, "invoiceEmail"),
            "phoneNumber": lookup_analysis_value(task_analysis, "phoneNumber", "phone"),
            "phoneNumberMobile": lookup_analysis_value(task_analysis, "phoneNumberMobile", "mobile"),
            "description": lookup_analysis_value(task_analysis, "description"),
        }
    )


def _sales_payload(task_analysis: TaskAnalysis, *, combined_text: str) -> dict[str, Any]:
    order_lines = _extract_order_lines(task_analysis)
    del combined_text
    operation = (task_analysis.operation or "").casefold()
    target_resource = (task_analysis.target_resource or "").casefold()
    return _drop_empty(
        {
            "customer": _customer_payload(task_analysis),
            "orderLines": order_lines,
            "orderDate": default_action_date(task_analysis, "orderDate", "date"),
            "deliveryDate": default_action_date(task_analysis, "deliveryDate", "orderDate", "date"),
            "invoiceDate": default_action_date(task_analysis, "invoiceDate", "orderDate", "date"),
            "invoiceDueDate": default_action_date(task_analysis, "invoiceDueDate", "paymentDate", "invoiceDate", "date"),
            "paymentDate": default_action_date(task_analysis, "paymentDate", "invoiceDate", "date"),
            "paymentTypeDescription": lookup_analysis_value(
                task_analysis,
                "paymentTypeDescription",
                "paymentTypeName",
                "paymentType",
                "paymentMethod",
            ),
            "createInvoice": bool(lookup_analysis_value(task_analysis, "createInvoice"))
            or target_resource == "invoice"
            or operation in {"invoice", "register_payment"},
            "registerPayment": bool(lookup_analysis_value(task_analysis, "registerPayment"))
            or operation == "register_payment",
        }
    )


def _supplier_invoice_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "supplier": {
                "name": lookup_analysis_value(task_analysis, "supplierName", "name"),
                "organizationNumber": lookup_analysis_value(
                    task_analysis,
                    "supplierOrganizationNumber",
                    "organizationNumber",
                ),
                "email": lookup_analysis_value(task_analysis, "supplierEmail", "email"),
                "invoiceEmail": lookup_analysis_value(task_analysis, "invoiceEmail"),
            },
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number", "externalId"),
            "description": lookup_analysis_value(
                task_analysis,
                "description",
                "invoiceDescription",
                "lineDescription",
            ),
            "accountNumber": lookup_analysis_value(
                task_analysis,
                "accountNumber",
                "ledgerAccountNumber",
                "postingAccount",
                "account",
            ),
            "amountIncludingVat": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "amountIncludingVat",
                    "amountInclVat",
                    "invoiceAmount",
                    "amountCurrency",
                    "amount",
                )
            ),
            "vatType": {
                "direction": "INCOMING",
                "percentage": _coerce_number(
                    lookup_analysis_value(
                        task_analysis,
                        "vatRate",
                        "vatPercentage",
                        "percentage",
                        "rate",
                    )
                ),
            },
            "invoiceDate": default_action_date(task_analysis, "invoiceDate", "date"),
            "dueDate": default_action_date(task_analysis, "dueDate", "paymentDate", "invoiceDate", "date"),
            "voucherTypeName": lookup_analysis_value(task_analysis, "voucherTypeName", "voucherType"),
        }
    )


def _payment_reversal_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "customer": _customer_payload(task_analysis),
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number"),
            "description": lookup_analysis_value(
                task_analysis,
                "description",
                "invoiceDescription",
                "lineDescription",
                "orderLineDescription",
            ),
            "amountExcludingVat": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "amountExcludingVat",
                    "amountExcludingVatCurrency",
                    "amount",
                )
            ),
            "reversalDate": default_action_date(task_analysis, "reversalDate", "paymentDate", "date"),
            "comment": lookup_analysis_value(task_analysis, "comment"),
        }
    )


def _invoice_credit_note_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "customer": _customer_payload(task_analysis),
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number"),
            "description": lookup_analysis_value(
                task_analysis,
                "description",
                "invoiceDescription",
                "lineDescription",
                "orderLineDescription",
            ),
            "amountExcludingVat": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "amountExcludingVat",
                    "amountExcludingVatCurrency",
                    "amount",
                )
            ),
            "creditNoteDate": default_action_date(task_analysis, "creditNoteDate", "date"),
            "comment": lookup_analysis_value(task_analysis, "comment", "creditNoteComment"),
        }
    )


def _invoice_payment_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number"),
            "customerId": lookup_analysis_value(task_analysis, "customerId", "customer_id"),
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name", "name"),
            "customerOrganizationNumber": lookup_analysis_value(
                task_analysis,
                "customerOrganizationNumber",
                "organizationNumber",
            ),
            "invoiceAmount": _coerce_number(lookup_analysis_value(task_analysis, "invoiceAmount", "amount")),
            "currencyCode": lookup_analysis_value(task_analysis, "currencyCode", "invoiceCurrency", "currency"),
            "invoiceDateFrom": lookup_analysis_value(task_analysis, "invoiceDateFrom"),
            "invoiceDateTo": lookup_analysis_value(task_analysis, "invoiceDateTo"),
        }
    )


def _invoice_payment_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "paymentDate": default_action_date(task_analysis, "paymentDate", "date"),
            "paidAmount": _coerce_number(
                lookup_analysis_value(
                    task_analysis,
                    "paidAmount",
                    "paymentAmount",
                    "amount",
                    "amountCurrency",
                )
            ),
            "paymentTypeDescription": lookup_analysis_value(
                task_analysis,
                "paymentTypeDescription",
                "paymentTypeName",
                "paymentType",
                "paymentMethod",
            ),
        }
    )


def _salary_payroll_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    arguments = _salary_payroll_method_arguments(task_analysis)
    return _drop_empty(
        {
            "email": arguments.get("employeeEmail"),
            "firstName": arguments.get("employeeFirstName"),
            "lastName": arguments.get("employeeLastName"),
            "count": 10,
        }
    )


def _salary_payroll_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    arguments = _salary_payroll_method_arguments(task_analysis)
    return _drop_empty(
        {
            "date": arguments.get("date"),
            "month": int(arguments["month"]) if arguments.get("month") not in {None, ""} else None,
            "year": int(arguments["year"]) if arguments.get("year") not in {None, ""} else None,
            "paySlipsAvailableDate": arguments.get("paySlipsAvailableDate"),
            "isHistorical": arguments.get("isHistorical"),
            "generateTaxDeduction": arguments.get("generateTaxDeduction"),
            "salaryLines": arguments.get("salaryLines"),
            "payslips": arguments.get("payslips"),
        }
    )


def _bank_reconciliation_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    arguments = _bank_reconciliation_method_arguments(task_analysis)
    return _drop_empty(
        {
            "bankAccountNumber": arguments.get("bankAccountNumber"),
            "bankRegisterNumber": arguments.get("bankRegisterNumber"),
            "bankName": arguments.get("bankName"),
            "fromDate": arguments.get("fromDate"),
            "toDate": arguments.get("toDate"),
        }
    )


def _bank_reconciliation_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    arguments = _bank_reconciliation_method_arguments(task_analysis)
    return _drop_empty(
        {
            "statementEntries": arguments.get("statementEntries"),
            "fromDate": arguments.get("fromDate"),
            "toDate": arguments.get("toDate"),
        }
    )


def _expense_increase_project_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    baseline_from = lookup_analysis_value(task_analysis, "baselineDateFrom")
    baseline_to = lookup_analysis_value(task_analysis, "baselineDateTo")
    comparison_from = lookup_analysis_value(task_analysis, "comparisonDateFrom")
    comparison_to = lookup_analysis_value(task_analysis, "comparisonDateTo")
    return _drop_empty(
        {
            "baselinePeriod": _drop_empty(
                {
                    "label": lookup_analysis_value(task_analysis, "baselineLabel"),
                    "dateFrom": baseline_from,
                    "dateTo": baseline_to,
                }
            ),
            "comparisonPeriod": _drop_empty(
                {
                    "label": lookup_analysis_value(task_analysis, "comparisonLabel"),
                    "dateFrom": comparison_from,
                    "dateTo": comparison_to,
                }
            ),
            "topCount": int(_coerce_number(lookup_analysis_value(task_analysis, "topCount")) or 3),
            "isInternal": lookup_analysis_value(task_analysis, "isInternal"),
            "createActivity": lookup_analysis_value(task_analysis, "createActivity"),
        }
    )


def _ledger_dimension_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    dimension_values = _extract_dimension_values(task_analysis)
    return _drop_empty(
        {
            "dimensionName": lookup_analysis_value(
                task_analysis,
                "dimensionName",
                "dimensionType",
                "dimension_type",
            ),
            "dimensionValues": dimension_values,
            "postingAccount": lookup_analysis_value(task_analysis, "postingAccount", "accountNumber"),
            "postingAmount": _coerce_number(lookup_analysis_value(task_analysis, "postingAmount", "amount")),
            "postingDimensionValue": lookup_analysis_value(
                task_analysis,
                "postingDimensionValue",
                "dimensionValue",
            ),
            "counterAccount": lookup_analysis_value(
                task_analysis,
                "counterAccount",
                "offsetAccount",
                "contraAccount",
                "creditAccount",
                "debitAccount",
            ),
            "voucherDate": default_action_date(task_analysis, "voucherDate", "date"),
            "voucherDescription": lookup_analysis_value(task_analysis, "voucherDescription", "description"),
            "currencyCode": lookup_analysis_value(task_analysis, "currencyCode", "currency", "currencyCodeIso"),
            "requiresVoucher": bool(lookup_analysis_value(task_analysis, "requiresVoucher"))
            or any(
                lookup_analysis_value(task_analysis, key) not in {None, ""}
                for key in ("postingAccount", "postingAmount", "postingDimensionValue", "counterAccount")
            ),
        }
    )


def _project_time_invoice_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    method_arguments = _project_time_invoice_method_arguments(task_analysis)
    customer_ref = _drop_empty(
        {
            "organizationNumber": method_arguments.get("customerOrganizationNumber"),
            "customerName": method_arguments.get("customerName"),
        }
    )
    employee_ref = _drop_empty(
        {
            "email": method_arguments.get("employeeEmail"),
            "firstName": method_arguments.get("employeeFirstName"),
            "lastName": method_arguments.get("employeeLastName"),
        }
    )
    project_ref = _drop_empty(
        {
            "name": method_arguments.get("projectName"),
            "number": method_arguments.get("projectNumber"),
        }
    )
    activity_ref = _drop_empty(
        {
            "name": method_arguments.get("activityName"),
            "number": method_arguments.get("activityNumber"),
        }
    )

    return _drop_empty(
        {
            "customerRef": customer_ref,
            "employeeRef": employee_ref,
            "projectRef": project_ref,
            "activityRef": activity_ref,
            "date": method_arguments.get("date"),
            "hours": method_arguments.get("hours"),
            "hourlyRate": method_arguments.get("hourlyRate"),
            "comment": method_arguments.get("comment"),
            "orderDate": method_arguments.get("orderDate"),
            "deliveryDate": method_arguments.get("deliveryDate") or method_arguments.get("orderDate"),
            "invoiceDate": method_arguments.get("invoiceDate"),
            "invoiceDueDate": method_arguments.get("invoiceDueDate") or method_arguments.get("invoiceDate"),
            "createInvoice": True,
        }
    )


def _project_lifecycle_payload(task_analysis: TaskAnalysis) -> dict[str, Any]:
    budget_amount = _coerce_number(
        lookup_analysis_value(task_analysis, "projectBudget", "budget", "budgetAmount", "fixedprice", "fixedPrice")
    )
    timesheet_entries = _extract_lifecycle_timesheet_entries(task_analysis)
    supplier_invoice_fields = _raw_supplier_invoice_fields(task_analysis)
    project_ref = _drop_empty(
        {
            "name": lookup_analysis_value(task_analysis, "projectName", "project_name", "name"),
            "number": lookup_analysis_value(task_analysis, "projectNumber", "number"),
            "description": lookup_analysis_value(task_analysis, "description"),
            "reference": lookup_analysis_value(task_analysis, "reference"),
            "startDate": lookup_analysis_value(task_analysis, "startDate"),
            "endDate": lookup_analysis_value(task_analysis, "endDate"),
            "invoiceReceiverEmail": lookup_analysis_value(task_analysis, "invoiceReceiverEmail"),
            "overdueNoticeEmail": lookup_analysis_value(task_analysis, "overdueNoticeEmail"),
            "isPriceCeiling": bool(budget_amount) or None,
            "priceCeilingAmount": budget_amount,
        }
    )
    customer_ref = _drop_empty(
        {
            "organizationNumber": lookup_analysis_value(
                task_analysis,
                "customer_organizationNumber",
                "customerOrganizationNumber",
                "organizationNumber",
            ),
            "customerName": lookup_analysis_value(task_analysis, "customerName", "customer_name"),
        }
    )
    if customer_ref:
        project_ref["customerRef"] = customer_ref

    department_ref = _drop_empty(
        {
            "departmentNumber": lookup_analysis_value(task_analysis, "departmentNumber"),
            "name": lookup_analysis_value(task_analysis, "departmentName"),
        }
    )
    if department_ref:
        project_ref["departmentRef"] = department_ref

    manager_ref = _drop_empty(
        {
            "email": lookup_analysis_value(task_analysis, "projectManagerEmail"),
            "firstName": lookup_analysis_value(task_analysis, "projectManagerFirstName"),
            "lastName": lookup_analysis_value(task_analysis, "projectManagerLastName"),
        }
    )
    if manager_ref:
        project_ref["projectManagerRef"] = manager_ref

    return _drop_empty(
        {
            "project": project_ref,
            "customerRef": customer_ref,
            "defaultActivity": {
                "name": lookup_analysis_value(task_analysis, "activityName", "activity_name") or "Project work",
                "isChargeable": True,
                "isProjectActivity": True,
            },
            "timesheetEntries": timesheet_entries,
            "supplierInvoice": supplier_invoice_fields,
            "invoice": {
                "invoiceDate": default_action_date(task_analysis, "invoiceDate", "date"),
                "invoiceDueDate": default_action_date(task_analysis, "invoiceDueDate", "paymentDate", "invoiceDate", "date"),
                "budgetAmount": budget_amount,
            },
        }
    )


def _extract_lifecycle_timesheet_entries(task_analysis: TaskAnalysis) -> list[dict[str, Any]]:
    raw_entries = lookup_analysis_value(task_analysis, "timesheetEntries", "timeEntries")
    entries: list[dict[str, Any]] = []
    if isinstance(raw_entries, list):
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            email = entry.get("employeeEmail") or entry.get("email")
            first_name = entry.get("employeeFirstName") or entry.get("firstName")
            last_name = entry.get("employeeLastName") or entry.get("lastName")
            if (first_name in {None, ""} or last_name in {None, ""}) and entry.get("employeeName") not in {None, ""}:
                parts = str(entry["employeeName"]).strip().split()
                if len(parts) >= 2:
                    first_name = parts[0]
                    last_name = " ".join(parts[1:])
            hours = _coerce_number(entry.get("hours"))
            if hours in {None, ""}:
                continue
            entries.append(
                _drop_empty(
                    {
                        "employeeRef": {
                            "email": email,
                            "firstName": first_name,
                            "lastName": last_name,
                        },
                        "hours": hours,
                        "hourlyRate": _coerce_number(entry.get("hourlyRate") or entry.get("hourlyWage")),
                        "date": entry.get("date") or default_action_date(task_analysis, "date"),
                        "comment": entry.get("comment"),
                        "activityName": entry.get("activityName") or lookup_analysis_value(task_analysis, "activityName", "activity_name"),
                    }
                )
            )
    if entries:
        return entries

    fallback_hours = _coerce_number(lookup_analysis_value(task_analysis, "hours"))
    if fallback_hours in {None, ""}:
        return []
    fallback_employee = _drop_empty(
        {
            "email": lookup_analysis_value(task_analysis, "employeeEmail", "employee_email", "email"),
            "firstName": lookup_analysis_value(task_analysis, "employeeFirstName", "firstName", "first_name"),
            "lastName": lookup_analysis_value(task_analysis, "employeeLastName", "lastName", "last_name"),
        }
    )
    if not fallback_employee:
        return []
    return [
        _drop_empty(
            {
                "employeeRef": fallback_employee,
                "hours": fallback_hours,
                "hourlyRate": _coerce_number(lookup_analysis_value(task_analysis, "hourlyRate", "hourlyWage")),
                "date": default_action_date(task_analysis, "date"),
                "comment": lookup_analysis_value(task_analysis, "comment"),
                "activityName": lookup_analysis_value(task_analysis, "activityName", "activity_name"),
            }
        )
    ]


def _raw_supplier_invoice_fields(task_analysis: TaskAnalysis) -> dict[str, Any]:
    raw_value = lookup_analysis_value(task_analysis, "supplierInvoice")
    if isinstance(raw_value, dict):
        supplier = raw_value.get("supplier") if isinstance(raw_value.get("supplier"), dict) else {}
        return _drop_empty(
            {
                "supplierName": raw_value.get("supplierName") or supplier.get("name"),
                "supplierOrganizationNumber": raw_value.get("supplierOrganizationNumber") or supplier.get("organizationNumber"),
                "supplierEmail": raw_value.get("supplierEmail") or supplier.get("email"),
                "invoiceNumber": raw_value.get("invoiceNumber"),
                "description": raw_value.get("description"),
                "accountNumber": raw_value.get("accountNumber"),
                "amountIncludingVat": _coerce_number(
                    raw_value.get("amountIncludingVat")
                    or raw_value.get("amountInclVat")
                    or raw_value.get("invoiceAmount")
                    or raw_value.get("amount")
                ),
                "vatRate": _coerce_number(
                    raw_value.get("vatRate")
                    or raw_value.get("vatPercentage")
                    or ((raw_value.get("vatType") or {}).get("percentage") if isinstance(raw_value.get("vatType"), dict) else None)
                ),
                "invoiceDate": raw_value.get("invoiceDate"),
                "dueDate": raw_value.get("dueDate"),
                "voucherTypeName": raw_value.get("voucherTypeName"),
            }
        )
    return _supplier_invoice_method_arguments(task_analysis)


def _extract_order_lines(task_analysis: TaskAnalysis) -> list[dict[str, Any]]:
    raw_order_lines = lookup_analysis_value(task_analysis, "orderLines")
    if isinstance(raw_order_lines, list):
        order_lines: list[dict[str, Any]] = []
        for index, entry in enumerate(raw_order_lines, start=1):
            if not isinstance(entry, dict):
                continue
            product_number = entry.get("productNumber") or entry.get("number")
            description = entry.get("description") or entry.get("name")
            unit_price = (
                entry.get("unitPriceExcludingVatCurrency")
                or entry.get("unitPriceExcludingVat")
                or entry.get("unitPrice")
                or entry.get("amount")
            )
            count = entry.get("count") or entry.get("quantity") or 1
            vat_type = _extract_vat_type_reference(entry)
            order_lines.append(
                _drop_empty(
                    {
                        "line_number": index,
                        "productNumber": str(product_number) if not _is_blank(product_number) else None,
                        "description": str(description or ""),
                        "unitPriceExcludingVatCurrency": _coerce_number(unit_price),
                        "count": _coerce_number(count) or 1,
                        "vatType": vat_type,
                    }
                )
            )
        if order_lines:
            return order_lines

    grouped: dict[int, dict[str, Any]] = {}
    for key, value in task_analysis.payload_fields.items():
        match = re.fullmatch(r"orderLine(\d+)_(.+)", str(key))
        if not match:
            continue
        line_number = int(match.group(1))
        grouped.setdefault(line_number, {"line_number": line_number})[match.group(2)] = value

    order_lines: list[dict[str, Any]] = []
    for line_number in sorted(grouped):
        entry = grouped[line_number]
        product_number = entry.get("productNumber")
        if product_number in {None, ""}:
            continue
        vat_type = _extract_vat_type_reference(entry)
        order_lines.append(
            _drop_empty(
                {
                    "line_number": line_number,
                    "productNumber": str(product_number),
                    "description": str(entry.get("description") or ""),
                    "unitPriceExcludingVatCurrency": _coerce_number(entry.get("unitPrice")),
                    "count": _coerce_number(entry.get("count")) or 1,
                    "vatType": vat_type,
                }
            )
        )
    return order_lines


def _extract_vat_type_reference(entry: dict[str, Any]) -> dict[str, Any] | None:
    nested_vat_type = entry.get("vatType")
    if isinstance(nested_vat_type, dict):
        return _drop_empty(
            {
                "id": nested_vat_type.get("id"),
                "number": nested_vat_type.get("number") or nested_vat_type.get("code"),
                "name": nested_vat_type.get("name"),
                "displayName": nested_vat_type.get("displayName"),
                "percentage": _coerce_number(
                    nested_vat_type.get("percentage") or nested_vat_type.get("vatRate") or nested_vat_type.get("rate")
                ),
            }
        ) or None

    return _drop_empty(
        {
            "id": entry.get("vatTypeId"),
            "number": entry.get("vatTypeNumber") or entry.get("vatCode"),
            "name": entry.get("vatTypeName"),
            "displayName": entry.get("vatTypeDisplayName"),
            "percentage": _coerce_number(
                entry.get("vatRate") or entry.get("vatPercentage") or entry.get("percentage")
            ),
        }
    ) or None


def _extract_dimension_values(task_analysis: TaskAnalysis) -> list[str]:
    raw_values = lookup_analysis_value(task_analysis, "dimensionValues")
    values: list[str] = []
    if isinstance(raw_values, list):
        values.extend(str(value).strip() for value in raw_values if not _is_blank(value))
    elif not _is_blank(raw_values):
        values.extend(part.strip() for part in str(raw_values).split(",") if part.strip())

    for key in ("postingDimensionValue", "dimensionValue"):
        value = lookup_analysis_value(task_analysis, key)
        if not _is_blank(value):
            values.append(str(value).strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(value)
    return deduped


def fastpath_task_analysis(*, task_prompt: str, attachments: list[AttachmentContext]) -> TaskAnalysis | None:
    del task_prompt, attachments
    return None


def _inclusive_iso_date_span(start_date: str, end_date: str) -> int | None:
    start = _best_effort_iso_date(start_date)
    end = _best_effort_iso_date(end_date)
    if start is None or end is None:
        return None
    if end < start:
        return None
    return (end - start).days + 1


def _derive_comparison_month_arguments(task_analysis: TaskAnalysis) -> dict[str, str]:
    if any(
        lookup_analysis_value(task_analysis, key) not in {None, ""}
        for key in ("baselineDateFrom", "baselineDateTo", "comparisonDateFrom", "comparisonDateTo")
    ):
        return {}

    overall_start = lookup_analysis_value(task_analysis, "dateFrom", "date_from")
    overall_end = lookup_analysis_value(task_analysis, "dateTo", "date_to")
    if overall_start in {None, ""} or overall_end in {None, ""}:
        return {}

    start = _best_effort_iso_date(overall_start)
    end = _best_effort_iso_date(overall_end)
    if start is None or end is None:
        return {}

    if start.day != 1 or end < start:
        return {}
    baseline_end = _last_day_of_month(start)
    comparison_start = baseline_end + timedelta(days=1)
    comparison_end = _last_day_of_month(comparison_start)
    if comparison_end != end:
        return {}
    return {
        "baselineDateFrom": start.isoformat(),
        "baselineDateTo": baseline_end.isoformat(),
        "comparisonDateFrom": comparison_start.isoformat(),
        "comparisonDateTo": comparison_end.isoformat(),
    }


def _last_day_of_month(value: date) -> date:
    if value.month == 12:
        return value.replace(day=31)
    next_month = value.replace(month=value.month + 1, day=1)
    return next_month - timedelta(days=1)


def _best_effort_iso_date(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
        if match is None:
            return None
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        if not 1 <= month <= 12:
            return None
        month_start = date(year, month, 1)
        clamped_day = min(max(day, 1), _last_day_of_month(month_start).day)
        try:
            return date(year, month, clamped_day)
        except ValueError:
            return None


def _drop_empty(mapping: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in mapping.items():
        if _is_blank(value):
            continue
        if isinstance(value, dict):
            nested = _drop_empty(value)
            if nested:
                cleaned[key] = nested
            continue
        if isinstance(value, list):
            if value:
                cleaned[key] = value
            continue
        cleaned[key] = value
    return cleaned


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _coerce_number(value: Any) -> float | None:
    if _is_blank(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None
