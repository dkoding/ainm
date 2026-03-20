from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .openapi_registry import OperationSpec, TripletexOpenAPIRegistry
from .tasking import TaskAnalysis, TripletexCommand


class _MissingSentinel:
    pass


_MISSING = _MissingSentinel()


LEDGER_PATH_ALIASES = {
    "/account": "/ledger/account",
    "/posting": "/ledger/posting",
    "/vatSettings": "/ledger/vatSettings",
    "/vatType": "/ledger/vatType",
    "/voucher": "/ledger/voucher",
}

PARAMETER_ALIASES: dict[tuple[str, str], dict[str, str]] = {
    ("GET", "/customer"): {
        "name": "customerName",
    },
    ("GET", "/invoice/paymentType"): {
        "name": "description",
    },
    ("GET", "/travelExpense/paymentType"): {
        "name": "description",
    },
    ("GET", "/ledger/paymentTypeOut"): {
        "name": "description",
    },
}

SALES_MODULE_NAMES = [
    "MAMUT",
    "MAMUT_WITH_WAGE",
    "AGRO_LICENCE",
    "AGRO_CLIENT",
    "AGRO_DOCUMENT_CENTER",
    "AGRO_INVOICE",
    "AGRO_INVOICE_MIGRATED",
    "AGRO_WAGE",
    "NO1TS",
    "NO1TS_TRAVELREPORT",
    "NO1TS_ACCOUNTING",
    "DIYPACKAGE",
    "BASIS",
    "SMART",
    "KOMPLETT",
    "VVS",
    "ELECTRO",
    "ACCOUNTING_OFFICE",
    "WAGE",
    "SMART_WAGE",
    "TIME_TRACKING",
    "SMART_TIME_TRACKING",
    "SMART_PROJECT",
    "OCR",
    "API_V2",
    "ELECTRONIC_VOUCHERS",
    "UP_TO_100_VOUCHERS",
    "UP_TO_500_VOUCHERS",
    "UP_TO_1000_VOUCHERS",
    "UP_TO_2000_VOUCHERS",
    "UP_TO_3500_VOUCHERS",
    "UP_TO_5000_VOUCHERS",
    "UP_TO_10000_VOUCHERS",
    "UNLIMITED_VOUCHERS",
    "UP_TO_100_VOUCHERS_AUTOMATION",
    "UP_TO_500_VOUCHERS_AUTOMATION",
    "UP_TO_1000_VOUCHERS_AUTOMATION",
    "UP_TO_2000_VOUCHERS_AUTOMATION",
    "UP_TO_3500_VOUCHERS_AUTOMATION",
    "UP_TO_5000_VOUCHERS_AUTOMATION",
    "UP_TO_10000_VOUCHERS_AUTOMATION",
    "UNLIMITED_VOUCHERS_AUTOMATION",
    "LOGISTICS",
    "MIKRO",
    "AUTOPLUS_MINI",
    "AUTOPLUS_MEDIUM",
    "AUTOPLUS_STOR",
    "INTEGRATION_PARTNER",
    "PROJECT",
    "YEAR_END_REPORTING_ENK",
    "YEAR_END_REPORTING_AS",
    "YEAR_END_REPORTING_ANS",
    "YEAR_END_REPORTING_DA",
    "YEAR_END_REPORTING_STI",
    "YEAR_END_REPORTING_ORG",
    "YEAR_END_REPORTING_SA",
    "YEAR_END_REPORTING_FLI",
    "YEAR_END_REPORTING_NUF",
    "PRIMARY_INDUSTRY",
    "STICOS",
    "PRO",
    "FIXED_ASSETS_REGISTER",
    "ZTL",
]

SALES_MODULE_ALIASES = {
    "accounting office": "ACCOUNTING_OFFICE",
    "api v2": "API_V2",
    "electronic vouchers": "ELECTRONIC_VOUCHERS",
    "ocr": "OCR",
    "project": "PROJECT",
    "salary": "WAGE",
    "time tracking": "TIME_TRACKING",
    "travel expense": "NO1TS_TRAVELREPORT",
    "travel report": "NO1TS_TRAVELREPORT",
    "wage": "WAGE",
}

ENTITLEMENT_TEMPLATES = {
    "ALL_PRIVILEGES": (
        "administrator",
        "admin",
        "all privileges",
        "full access",
        "kontoadministrator",
    ),
    "ACCOUNTANT": (
        "accountant",
        "regnskapsforer",
        "regnskapsfører",
    ),
    "AUDITOR": (
        "auditor",
        "revisor",
    ),
    "DEPARTMENT_LEADER": (
        "department leader",
        "department manager",
        "avdelingsleder",
    ),
    "INVOICING_MANAGER": (
        "billing manager",
        "invoice manager",
        "invoicing manager",
    ),
    "PERSONELL_MANAGER": (
        "hr",
        "personnel manager",
        "personell",
    ),
}


@dataclass(frozen=True)
class CommandRepairResult:
    command: TripletexCommand
    notes: tuple[str, ...] = ()


def planner_runtime_hints(task_analysis: TaskAnalysis | None = None) -> dict[str, Any]:
    hints: dict[str, Any] = {
        "authoritative_rule": "Treat the OpenAPI spec as authoritative. The examples docs are illustrative and may use simplified names or flows. Lack of a curated shortcut method does not imply lack of API support.",
        "known_path_aliases": {
            wrong: correct for wrong, correct in sorted(LEDGER_PATH_ALIASES.items())
        },
        "known_parameter_aliases": [
            {
                "method": method,
                "path": path,
                "aliases": aliases,
            }
            for (method, path), aliases in sorted(PARAMETER_ALIASES.items())
        ],
        "required_date_windows": {
            "/invoice": ["invoiceDateFrom", "invoiceDateTo"],
            "/ledger/voucher": ["dateFrom", "dateTo"],
            "/order": ["orderDateFrom", "orderDateTo"],
        },
        "payment_workflow_notes": [
            "Do not use POST /payment. Outgoing invoice payment uses PUT /invoice/{id}/:payment.",
            "Supplier invoice payment uses POST /supplierInvoice/{invoiceId}/:addPayment.",
            "Incoming invoice or voucher payment uses POST /incomingInvoice/{voucherId}/addPayment.",
        ],
        "composite_workflow_patterns": [
            {
                "name": "sales_invoice",
                "when": "customer billing, invoicing, or order-based sales tasks",
                "steps": [
                    "resolve or create the customer",
                    "resolve or create referenced products when order lines require them",
                    "create or update the order",
                    "create the invoice through PUT /order/{id}/:invoice or POST /invoice when appropriate",
                ],
            },
            {
                "name": "invoice_payment",
                "when": "register payment for an outgoing invoice",
                "steps": [
                    "resolve the invoice",
                    "resolve the payment type if needed",
                    "register payment with PUT /invoice/{id}/:payment",
                ],
            },
            {
                "name": "project_time_billing",
                "when": "register project hours, timesheet entries, activities, or bill a project from registered hours",
                "steps": [
                    "resolve employee, project, and activity for the relevant date",
                    "create or update timesheet entries with /timesheet/entry or /timesheet/entry/list",
                    "then create the billing artifact through project, order, and invoice methods as required by the task",
                ],
            },
            {
                "name": "linked_project_setup",
                "when": "create or update a project with customer, department, or project manager references",
                "steps": [
                    "resolve linked customer, department, and employee references first",
                    "then create or update the project",
                ],
            },
            {
                "name": "travel_expense",
                "when": "travel expense and reimbursement workflows",
                "steps": [
                    "resolve employee and project references if present",
                    "create or update the travel expense",
                    "use payment-type endpoints when reimbursement payment data is required",
                ],
            },
            {
                "name": "ledger_adjustment",
                "when": "voucher, posting, reconciliation, or accounting-dimension tasks",
                "steps": [
                    "resolve required accounts, dimensions, and related entities",
                    "create or update ledger postings or vouchers",
                    "verify the resulting ledger state when the task requires correction or reconciliation",
                ],
            },
        ],
    }

    if task_analysis is None:
        return hints

    combined_text = combine_analysis_text(task_analysis)
    if is_invoice_payment_task(task_analysis):
        hints["related_endpoints"] = [
            "/invoice",
            "/invoice/paymentType",
            "/invoice/{id}/:payment",
            "/supplierInvoice/{invoiceId}/:addPayment",
            "/incomingInvoice/{voucherId}/addPayment",
        ]
    if is_employee_admin_task(task_analysis, combined_text=combined_text):
        hints["entitlement_templates"] = sorted(ENTITLEMENT_TEMPLATES.keys())
        hints["employee_admin_notes"] = [
            "Administrator-like tasks may require /employee/entitlement endpoints, not only employee CRUD.",
            "ALL_PRIVILEGES typically implies userType EXTENDED on the employee.",
        ]
    if looks_like_module_task(task_analysis, combined_text=combined_text):
        hints["sales_module_names"] = SALES_MODULE_NAMES
        hints["sales_module_aliases"] = SALES_MODULE_ALIASES
    return hints


def repair_command(
    command: TripletexCommand,
    *,
    task_analysis: TaskAnalysis,
    history: list[dict[str, Any]],
    registry: TripletexOpenAPIRegistry,
) -> CommandRepairResult:
    repaired = command
    notes: list[str] = []

    new_path = _rewrite_path_alias(repaired.path)
    if new_path != repaired.path:
        notes.append(f"path:{repaired.path}->{new_path}")
        repaired = _replace_command(repaired, path=new_path)

    operation = registry.match_operation(method=repaired.method, path=repaired.path)
    if operation is None:
        return CommandRepairResult(command=repaired, notes=tuple(notes))

    rewritten_params = _rewrite_parameter_aliases(repaired, operation)
    if rewritten_params != (repaired.params or {}):
        notes.append("query_aliases")
        repaired = _replace_command(repaired, params=rewritten_params)

    synthesized_params = _synthesize_required_params(
        repaired,
        operation=operation,
        task_analysis=task_analysis,
        history=history,
    )
    if synthesized_params != (repaired.params or {}):
        notes.append("required_query_defaults")
        repaired = _replace_command(repaired, params=synthesized_params)

    return CommandRepairResult(command=repaired, notes=tuple(notes))


def combine_analysis_text(task_analysis: TaskAnalysis) -> str:
    parts: list[str] = [
        task_analysis.objective,
        task_analysis.task_family,
        task_analysis.operation,
        task_analysis.target_resource or "",
        " ".join(task_analysis.ambiguity_notes),
        " ".join(task_analysis.completion_signals),
        " ".join(task_analysis.notes),
    ]
    for mapping in (task_analysis.search_hints, task_analysis.payload_fields):
        for value in mapping.values():
            if value is None:
                continue
            parts.append(str(value))
    return " ".join(part for part in parts if part).lower()


def is_invoice_payment_task(task_analysis: TaskAnalysis) -> bool:
    if task_analysis.target_resource == "invoice" and task_analysis.operation == "register_payment":
        return True
    family = task_analysis.task_family.lower()
    return "invoice" in family and "payment" in family


def is_employee_admin_task(task_analysis: TaskAnalysis, *, combined_text: str | None = None) -> bool:
    if (task_analysis.target_resource or "").lower() != "employee":
        return False
    text = combined_text or combine_analysis_text(task_analysis)
    return any(keyword in text for values in ENTITLEMENT_TEMPLATES.values() for keyword in values)


def looks_like_module_task(task_analysis: TaskAnalysis, *, combined_text: str | None = None) -> bool:
    text = combined_text or combine_analysis_text(task_analysis)
    return any(token in text for token in ("module", "activate", "enable", "sales module"))


def infer_entitlement_template(task_analysis: TaskAnalysis, *, prompt_text: str = "") -> str | None:
    combined_text = " ".join(part for part in (prompt_text, combine_analysis_text(task_analysis)) if part).lower()
    for template, keywords in ENTITLEMENT_TEMPLATES.items():
        if any(keyword in combined_text for keyword in keywords):
            return template
    if "admin" in combined_text or "administrator" in combined_text:
        return "ALL_PRIVILEGES"
    return None


def normalize_sales_module_name(*, prompt_text: str = "", task_analysis: TaskAnalysis | None = None) -> str | None:
    combined = " ".join(
        part for part in (prompt_text, combine_analysis_text(task_analysis) if task_analysis else "") if part
    ).upper()
    for name in SALES_MODULE_NAMES:
        if name in combined:
            return name

    lowered = combined.lower()
    for alias, name in SALES_MODULE_ALIASES.items():
        if alias in lowered:
            return name
    return None


def best_effort_amount(task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    for key in (
        "paidAmount",
        "paid_amount",
        "paymentAmount",
        "payment_amount",
        "amount",
        "amountCurrency",
        "sum",
    ):
        value = lookup_analysis_value(task_analysis, key)
        if value not in {None, ""}:
            return value

    invoice = resolved_invoice_from_history(history, task_analysis)
    if invoice is None:
        return None
    for key in ("amountCurrency", "amount", "paidAmount"):
        value = invoice.get(key)
        if value not in {None, ""}:
            return value
    return None


def best_effort_payment_type_id(task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    for key in ("paymentTypeId", "payment_type_id", "paymentType"):
        value = lookup_analysis_value(task_analysis, key)
        if value not in {None, ""}:
            return value

    invoice = resolved_invoice_from_history(history, task_analysis)
    if invoice is not None and invoice.get("paymentTypeId") not in {None, ""}:
        return invoice["paymentTypeId"]

    desired_description = best_effort_payment_type_description(task_analysis)
    desired_lower = desired_description.lower() if desired_description else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        if path not in {"/invoice/paymentType", "/travelExpense/paymentType", "/ledger/paymentTypeOut"}:
            continue
        values = [candidate for candidate in (response.get("values") or []) if isinstance(candidate, dict)]
        if desired_lower:
            for candidate in values:
                description = str(candidate.get("description") or candidate.get("displayName") or "").lower()
                if desired_lower in description and candidate.get("id") not in {None, ""}:
                    return candidate["id"]
        if len(values) == 1 and values[0].get("id") not in {None, ""}:
            return values[0]["id"]
    return None


def best_effort_payment_type_description(task_analysis: TaskAnalysis) -> str | None:
    for key in (
        "paymentTypeDescription",
        "paymentTypeName",
        "paymentMethod",
        "paymentMethodName",
        "paymentType",
    ):
        value = lookup_analysis_value(task_analysis, key)
        if value not in {None, ""}:
            return str(value)
    return None


def lookup_analysis_value(task_analysis: TaskAnalysis, *keys: str) -> Any | None:
    for mapping in (task_analysis.payload_fields, task_analysis.search_hints):
        for key in keys:
            if key in mapping and mapping[key] not in {None, ""}:
                return mapping[key]
    for mapping in (task_analysis.payload_fields, task_analysis.search_hints):
        lowered = {str(key).lower(): value for key, value in mapping.items()}
        for key in keys:
            value = lowered.get(key.lower())
            if value not in {None, ""}:
                return value
    return None


def resolved_invoice_from_history(history: list[dict[str, Any]], task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    requested_number = lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number", "number")
    requested_number = str(requested_number) if requested_number not in {None, ""} else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        if method == "GET" and path == "/invoice":
            values = response.get("values") or []
            if not isinstance(values, list):
                continue
            if requested_number:
                for candidate in values:
                    if isinstance(candidate, dict) and str(candidate.get("invoiceNumber")) == requested_number:
                        return candidate
            if len(values) == 1 and isinstance(values[0], dict):
                return values[0]
        if method == "GET" and path.startswith("/invoice/") and isinstance(response.get("value"), dict):
            return response["value"]
    return None


def best_effort_date_window(task_analysis: TaskAnalysis, *, start_key: str, end_key: str) -> tuple[str, str]:
    explicit_start = lookup_analysis_value(task_analysis, start_key, "dateFrom")
    explicit_end = lookup_analysis_value(task_analysis, end_key, "dateTo")
    if explicit_start and explicit_end:
        return str(explicit_start), str(explicit_end)

    for single_key in ("invoiceDate", "orderDate", "paymentDate", "date"):
        single_date = lookup_analysis_value(task_analysis, single_key)
        normalized = _normalize_date(single_date)
        if normalized is not None:
            return normalized, normalized

    return "2000-01-01", "2100-12-31"


def default_action_date(task_analysis: TaskAnalysis, *keys: str) -> str:
    value = lookup_analysis_value(task_analysis, *keys)
    normalized = _normalize_date(value)
    if normalized is not None:
        return normalized
    return date.today().isoformat()


def _rewrite_path_alias(path: str) -> str:
    for wrong_prefix, correct_prefix in LEDGER_PATH_ALIASES.items():
        if path == wrong_prefix or path.startswith(f"{wrong_prefix}/"):
            return f"{correct_prefix}{path[len(wrong_prefix):]}"
    return path


def _rewrite_parameter_aliases(command: TripletexCommand, operation: OperationSpec) -> dict[str, Any]:
    params = dict(command.params or {})
    aliases = PARAMETER_ALIASES.get((command.method, operation.template_path))
    if not aliases:
        return params

    for wrong_name, correct_name in aliases.items():
        if wrong_name in params and correct_name not in params:
            params[correct_name] = params.pop(wrong_name)
    return params


def _synthesize_required_params(
    command: TripletexCommand,
    *,
    operation: OperationSpec,
    task_analysis: TaskAnalysis,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    params = dict(command.params or {})

    missing = {
        name for name in operation.required_query_parameters if params.get(name) in {None, ""}
    }
    if not missing:
        return params

    if operation.template_path == "/invoice":
        start, end = best_effort_date_window(
            task_analysis,
            start_key="invoiceDateFrom",
            end_key="invoiceDateTo",
        )
        params.setdefault("invoiceDateFrom", start)
        params.setdefault("invoiceDateTo", end)
    elif operation.template_path == "/order":
        start, end = best_effort_date_window(
            task_analysis,
            start_key="orderDateFrom",
            end_key="orderDateTo",
        )
        params.setdefault("orderDateFrom", start)
        params.setdefault("orderDateTo", end)
    elif operation.template_path == "/ledger/voucher":
        start, end = best_effort_date_window(
            task_analysis,
            start_key="dateFrom",
            end_key="dateTo",
        )
        params.setdefault("dateFrom", start)
        params.setdefault("dateTo", end)
    elif operation.template_path == "/order/{id}/:invoice":
        params.setdefault("invoiceDate", default_action_date(task_analysis, "invoiceDate", "date"))
    elif operation.template_path == "/invoice/{id}/:payment":
        params.setdefault("paymentDate", default_action_date(task_analysis, "paymentDate", "date"))
        amount = best_effort_amount(task_analysis, history)
        if amount not in {None, ""}:
            params.setdefault("paidAmount", amount)
        payment_type_id = best_effort_payment_type_id(task_analysis, history)
        if payment_type_id not in {None, ""}:
            params.setdefault("paymentTypeId", payment_type_id)

    return params


def _replace_command(
    command: TripletexCommand,
    *,
    path: str | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = _MISSING,
) -> TripletexCommand:
    if json_body is _MISSING:
        next_json = command.json_body
    else:
        next_json = json_body
    return TripletexCommand(
        method=command.method,
        path=path if path is not None else command.path,
        reason=command.reason,
        params=params if params is not None else command.params,
        json_body=next_json,
    )


def _normalize_date(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None
