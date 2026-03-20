from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .spec_runtime import (
    combine_analysis_text,
    default_action_date,
    infer_entitlement_template,
    is_employee_admin_task,
    is_invoice_payment_task,
    lookup_analysis_value as _legacy_lookup_analysis_value,
)
from .tasking import TaskAnalysis


class FlowKind(str, Enum):
    SALES_WORKFLOW = "sales.workflow"
    PROJECT_TIME_INVOICE_WORKFLOW = "project.time_invoice.workflow"
    INVOICE_REGISTER_PAYMENT = "invoice.register_payment"
    EMPLOYEE_ADMIN = "employee.admin"
    EMPLOYEE_UPSERT = "employee.upsert"
    CUSTOMER_UPSERT = "customer.upsert"
    PRODUCT_UPSERT = "product.upsert"
    DEPARTMENT_UPSERT = "department.upsert"
    PROJECT_UPSERT = "project.upsert"
    LEDGER_DIMENSION_WORKFLOW = "ledger.dimension.workflow"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MethodSpec:
    name: str
    flow_kind: FlowKind
    operation: str
    target_resource: str
    description: str
    required_arguments: tuple[str, ...] = ()
    required_one_of: tuple[tuple[str, ...], ...] = ()
    optional_arguments: tuple[str, ...] = ()


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
            "invoiceDate",
            "paymentDate",
            "paymentTypeDescription",
            "createInvoice",
            "registerPayment",
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
            "orderDate",
        ),
    ),
    "RegisterInvoicePayment": MethodSpec(
        name="RegisterInvoicePayment",
        flow_kind=FlowKind.INVOICE_REGISTER_PAYMENT,
        operation="register_payment",
        target_resource="invoice",
        description="Register payment on an outgoing invoice.",
        required_arguments=("paidAmount",),
        required_one_of=(("invoiceNumber", "customerId"),),
        optional_arguments=("paymentDate", "paymentTypeDescription", "paymentTypeId"),
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
    ),
}


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
            }
        )
    return hints


def normalize_task_analysis_method_selection(*, task_prompt: str, task_analysis: TaskAnalysis) -> TaskAnalysis:
    normalized_method_name = _normalize_method_name(task_analysis.method_name)
    normalized_analysis = task_analysis

    if normalized_method_name != task_analysis.method_name:
        normalized_analysis = normalized_analysis.model_copy(update={"method_name": normalized_method_name})

    combined_text = combine_analysis_text(normalized_analysis)
    if _looks_like_time_tracking_invoice_request(
        task_prompt=task_prompt,
        task_analysis=normalized_analysis,
        combined_text=combined_text,
    ) and normalized_method_name in {"UnknownMethod", "RunSalesWorkflow"}:
        synthesized_arguments = dict(normalized_analysis.method_arguments or {})
        synthesized_arguments.update(_project_time_invoice_method_arguments(normalized_analysis))
        normalized_analysis = normalized_analysis.model_copy(
            update={
                "method_name": "RunProjectTimeInvoiceWorkflow",
                "method_arguments": _drop_empty(synthesized_arguments),
                "missing_required_arguments": [],
            }
        )
        normalized_method_name = "RunProjectTimeInvoiceWorkflow"

    method_spec = METHOD_SPECS.get(normalized_method_name)
    if method_spec is None:
        if normalized_method_name != "UnknownMethod":
            return normalized_analysis.model_copy(update={"method_name": "UnknownMethod"})
        return normalized_analysis

    if not _should_reject_supported_method(
        method_name=method_spec.name,
        task_prompt=task_prompt,
        task_analysis=normalized_analysis,
        combined_text=combined_text,
    ):
        return normalized_analysis

    notes = list(normalized_analysis.notes)
    notes.append(
        "Curated method routing was rejected because the selected supported method does not cover the full requested workflow."
    )
    fallback_method_name = "UnknownMethod"
    fallback_arguments: dict[str, Any] = {}
    if method_spec.name == "RunSalesWorkflow" and _looks_like_time_tracking_invoice_request(
        task_prompt=task_prompt,
        task_analysis=normalized_analysis,
        combined_text=combined_text,
    ):
        fallback_method_name = "RunProjectTimeInvoiceWorkflow"
        fallback_arguments = _project_time_invoice_method_arguments(normalized_analysis)

    return normalized_analysis.model_copy(
        update={
            "method_name": fallback_method_name,
            "method_arguments": _drop_empty(fallback_arguments),
            "missing_required_arguments": [],
            "notes": _dedupe_strings(notes),
        }
    )


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


def derive_internal_task(*, task_prompt: str, task_analysis: TaskAnalysis) -> InternalTask:
    task_analysis = normalize_task_analysis_method_selection(
        task_prompt=task_prompt,
        task_analysis=task_analysis,
    )
    combined_text = combine_analysis_text(task_analysis)
    extracted_method_name = _normalize_method_name(task_analysis.method_name)
    method_spec = METHOD_SPECS.get(extracted_method_name)

    if method_spec is not None:
        method_name = method_spec.name
        flow_kind = method_spec.flow_kind
        operation = method_spec.operation
        target_resource = method_spec.target_resource
    else:
        flow_kind = _infer_flow_kind(task_prompt=task_prompt, task_analysis=task_analysis, combined_text=combined_text)
        operation = (task_analysis.operation or "other").lower()
        target_resource = (task_analysis.target_resource or "other").lower()
        method_name = "UnknownMethod"

    search: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    notes: list[str] = []

    if flow_kind is FlowKind.CUSTOMER_UPSERT:
        search = _customer_search(task_analysis)
        payload = _customer_payload(task_analysis)
    elif flow_kind is FlowKind.PRODUCT_UPSERT:
        search = _product_search(task_analysis)
        payload = _product_payload(task_analysis)
    elif flow_kind is FlowKind.EMPLOYEE_UPSERT:
        search = _employee_search(task_analysis)
        payload = _employee_payload(task_analysis)
    elif flow_kind is FlowKind.EMPLOYEE_ADMIN:
        search = _employee_search(task_analysis)
        payload = _employee_payload(task_analysis)
        template = infer_entitlement_template(task_analysis, prompt_text=task_prompt)
        if template:
            payload["template"] = template
    elif flow_kind is FlowKind.DEPARTMENT_UPSERT:
        search = _department_search(task_analysis)
        payload = _department_payload(task_analysis)
    elif flow_kind is FlowKind.PROJECT_UPSERT:
        search = _project_search(task_analysis)
        payload = _project_payload(task_analysis)
    elif flow_kind is FlowKind.SALES_WORKFLOW:
        search = _sales_search(task_analysis)
        payload = _sales_payload(task_analysis, combined_text=combined_text)
    elif flow_kind is FlowKind.PROJECT_TIME_INVOICE_WORKFLOW:
        payload = _project_time_invoice_payload(task_analysis)
    elif flow_kind is FlowKind.INVOICE_REGISTER_PAYMENT:
        search = _invoice_payment_search(task_analysis)
        payload = _invoice_payment_payload(task_analysis)
    elif flow_kind is FlowKind.LEDGER_DIMENSION_WORKFLOW:
        payload = _ledger_dimension_payload(task_analysis, combined_text=combined_text)
        if payload.get("requiresVoucher") and payload.get("counterAccount") in {None, ""}:
            notes.append("Voucher creation requires a balancing counterAccount so the postings sum to zero.")

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


def _infer_flow_kind(*, task_prompt: str, task_analysis: TaskAnalysis, combined_text: str) -> FlowKind:
    family = task_analysis.task_family.lower()
    resource = (task_analysis.target_resource or "").lower()
    operation = (task_analysis.operation or "").lower()
    payload_keys = {str(key).lower() for key in task_analysis.payload_fields}
    prompt_text = task_prompt.lower()
    text = " ".join(part for part in (combined_text, prompt_text, family) if part)

    if is_invoice_payment_task(task_analysis):
        return FlowKind.INVOICE_REGISTER_PAYMENT

    if is_employee_admin_task(task_analysis, combined_text=text):
        return FlowKind.EMPLOYEE_ADMIN

    if _looks_like_time_tracking_invoice_request(
        task_prompt=task_prompt,
        task_analysis=task_analysis,
        combined_text=combined_text,
    ):
        return FlowKind.PROJECT_TIME_INVOICE_WORKFLOW

    if (
        resource in {"order", "invoice"}
        or "order" in family
        or any(key.startswith("orderline") for key in payload_keys)
    ) and any(token in text for token in ("order", "invoice", "faktura", "betaling", "payment")):
        return FlowKind.SALES_WORKFLOW

    if resource == "employee" and (operation in {"create", "update"} or family.startswith("employee.")):
        return FlowKind.EMPLOYEE_UPSERT
    if resource == "customer" and (operation in {"create", "update"} or family.startswith("customer.")):
        return FlowKind.CUSTOMER_UPSERT
    if resource == "product" and (operation in {"create", "update"} or family.startswith("product.")):
        return FlowKind.PRODUCT_UPSERT
    if resource == "department" and (operation in {"create", "update"} or family.startswith("department.")):
        return FlowKind.DEPARTMENT_UPSERT
    if resource == "project" and (operation in {"create", "update"} or family.startswith("project.")):
        return FlowKind.PROJECT_UPSERT
    if resource == "ledger" and any(
        token in text
        for token in (
            "accounting dimension",
            "dimension value",
            "regnskapsdimensjon",
            "fri regnskapsdimensjon",
            "accountingdimension",
        )
    ):
        return FlowKind.LEDGER_DIMENSION_WORKFLOW

    return FlowKind.UNKNOWN


def _normalize_method_name(value: Any) -> str:
    if _is_blank(value):
        return "UnknownMethod"
    compact = "".join(character for character in str(value) if character.isalnum()).lower()
    for method_name in METHOD_SPECS:
        if "".join(character for character in method_name if character.isalnum()).lower() == compact:
            return method_name
    return str(value)


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
    task_prompt: str,
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
        task_prompt=task_prompt,
        task_analysis=task_analysis,
        combined_text=combined_text,
    ):
        return True

    return False


def _looks_like_time_tracking_invoice_request(
    *,
    task_prompt: str,
    task_analysis: TaskAnalysis,
    combined_text: str,
) -> bool:
    text = " ".join(
        (
            task_prompt,
            combined_text,
            " ".join(task_analysis.ambiguity_notes),
        )
    ).lower()
    field_keys = {
        *(str(key).lower() for key in task_analysis.method_arguments),
        *(str(key).lower() for key in task_analysis.search_hints),
        *(str(key).lower() for key in task_analysis.payload_fields),
    }
    has_time_tracking_markers = any(
        token in text
        for token in (
            "register hours",
            "record hours",
            "timesheet",
            "time sheet",
            "time registration",
            "hour registration",
            "activity",
            "activite",
            "heures",
            "hours",
            "timer",
        )
    ) or any(
        key in field_keys
        for key in (
            "employeeemail",
            "activityname",
            "projectname",
            "hours",
            "hourlyrate",
        )
    )
    has_invoice_markers = (
        (task_analysis.operation or "").lower() == "invoice"
        or (task_analysis.target_resource or "").lower() == "invoice"
        or any(token in text for token in ("invoice", "faktura", "facture", "invoic"))
    )
    has_project_billing_context = any(
        token in text
        for token in (
            "project invoice",
            "invoice de projet",
            "facture de projet",
            "prosjektfaktura",
            "project hours",
            "project activity",
        )
    ) or any(
        key in field_keys
        for key in (
            "projectname",
            "activityname",
            "employeeemail",
        )
    )
    return has_time_tracking_markers and has_invoice_markers and has_project_billing_context


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
            "phoneNumberMobile": lookup_analysis_value(task_analysis, "phoneNumberMobile", "mobile"),
            "phoneNumberWork": lookup_analysis_value(task_analysis, "phoneNumber", "phone"),
            "comments": lookup_analysis_value(task_analysis, "comments", "comment"),
        }
    )

    user_type = lookup_analysis_value(task_analysis, "userType")
    if user_type not in {None, ""}:
        payload["userType"] = user_type
    return payload


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


def _sales_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _customer_search(task_analysis)


def _sales_payload(task_analysis: TaskAnalysis, *, combined_text: str) -> dict[str, Any]:
    order_lines = _extract_order_lines(task_analysis)
    payment_tokens = ("payment", "paid", "full payment", "register payment", "betal", "betalt")
    invoice_tokens = ("invoice", "faktura", "invoic")
    return _drop_empty(
        {
            "customer": _customer_payload(task_analysis),
            "orderLines": order_lines,
            "orderDate": default_action_date(task_analysis, "orderDate", "date"),
            "invoiceDate": default_action_date(task_analysis, "invoiceDate", "orderDate", "date"),
            "paymentDate": default_action_date(task_analysis, "paymentDate", "invoiceDate", "date"),
            "paymentTypeDescription": lookup_analysis_value(
                task_analysis,
                "paymentTypeDescription",
                "paymentTypeName",
                "paymentType",
                "paymentMethod",
            ),
            "createInvoice": any(token in combined_text for token in invoice_tokens)
            or (task_analysis.target_resource or "").lower() == "invoice",
            "registerPayment": any(token in combined_text for token in payment_tokens)
            or task_analysis.operation == "register_payment",
        }
    )


def _invoice_payment_search(task_analysis: TaskAnalysis) -> dict[str, Any]:
    return _drop_empty(
        {
            "invoiceNumber": lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number"),
            "customerId": lookup_analysis_value(task_analysis, "customerId", "customer_id"),
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


def _ledger_dimension_payload(task_analysis: TaskAnalysis, *, combined_text: str) -> dict[str, Any]:
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
            "requiresVoucher": any(
                token in combined_text
                for token in ("voucher", "bilag", "journal entry", "post", "posting")
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
            "invoiceDate": method_arguments.get("invoiceDate"),
            "createInvoice": True,
        }
    )


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
            order_lines.append(
                _drop_empty(
                    {
                        "line_number": index,
                        "productNumber": str(product_number) if not _is_blank(product_number) else None,
                        "description": str(description or ""),
                        "unitPriceExcludingVatCurrency": _coerce_number(unit_price),
                        "count": _coerce_number(count) or 1,
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
        order_lines.append(
            _drop_empty(
                {
                    "line_number": line_number,
                    "productNumber": str(product_number),
                    "description": str(entry.get("description") or ""),
                    "unitPriceExcludingVatCurrency": _coerce_number(entry.get("unitPrice")),
                    "count": _coerce_number(entry.get("count")) or 1,
                }
            )
        )
    return order_lines


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
