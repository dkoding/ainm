from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

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

REFERENCE_RESOLVER_KEYS = {
    "account": "ledger_account",
    "activity": "activity",
    "asset": "asset",
    "contact": "contact",
    "currency": "currency",
    "customer": "customer",
    "department": "department",
    "division": "division",
    "employee": "employee",
    "paymenttype": "payment_type",
    "product": "product",
    "project": "project",
    "projectmanager": "employee",
    "supplier": "supplier",
    "vattype": "vat_type",
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
        "reference_resolution_rules": [
            "Tripletex nested DTOs often display many fields, but existing related objects should usually be referenced by internal id only during POST and PUT requests.",
            "Resolve existing linked entities such as customer, supplier, employee, project, department, activity, product, account, vatType, and paymentType before using them in write payloads.",
            "If history already contains a unique resolved entity, prefer reusing that id instead of repeating human-readable nested fields in the write body.",
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
                "name": "purchase_order",
                "when": "procurement, supplier ordering, goods receipt, or purchase-order workflows",
                "steps": [
                    "resolve supplier and referenced product entities first",
                    "create or update the purchase order",
                    "continue with goods receipt or supplier-invoice methods when the task requires receiving or billing the order",
                ],
            },
            {
                "name": "inventory_control",
                "when": "stock counts, inventory adjustments, or warehouse inventory workflows",
                "steps": [
                    "resolve the relevant products, inventory items, and locations first",
                    "create or update the inventory counting or adjustment records",
                    "verify the resulting stock state when the task explicitly asks for confirmation",
                ],
            },
            {
                "name": "salary_payroll",
                "when": "salary, payroll, wage, or compensation workflows",
                "steps": [
                    "resolve employee and entitlement context first",
                    "use salary and employee endpoints together rather than forcing the task through generic invoice or ledger flows",
                    "continue with ledger-side verification only when the task explicitly requires accounting confirmation",
                ],
            },
            {
                "name": "fixed_assets",
                "when": "asset register or fixed-asset workflows",
                "steps": [
                    "resolve the target asset and related ledger context first",
                    "create or update the asset record",
                    "use ledger or year-end methods only when the task explicitly requires accounting follow-up",
                ],
            },
            {
                "name": "document_archive",
                "when": "document archive or attachment workflows",
                "steps": [
                    "resolve the owning entity first",
                    "use document-archive endpoints to create, update, or fetch the document artifact",
                    "link the archived document back to the requested business object when the task requires that association",
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

    repaired_body = _repair_body_references(repaired.json_body, task_analysis=task_analysis, history=history)
    if repaired_body != repaired.json_body:
        notes.append("body_reference_ids")
        repaired = _replace_command(repaired, json_body=repaired_body)

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
            if key in mapping and _has_analysis_value(mapping[key]):
                return mapping[key]
    for mapping in (task_analysis.payload_fields, task_analysis.search_hints):
        lowered = {str(key).lower(): value for key, value in mapping.items()}
        for key in keys:
            value = lowered.get(key.lower())
            if _has_analysis_value(value):
                return value
    return None


def _has_analysis_value(value: Any) -> bool:
    return value is not None and value != ""


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


def _repair_body_references(
    value: Any,
    *,
    task_analysis: TaskAnalysis,
    history: list[dict[str, Any]],
    key_hint: str = "",
) -> Any:
    if isinstance(value, list):
        repaired_items = [
            _repair_body_references(item, task_analysis=task_analysis, history=history, key_hint=key_hint)
            for item in value
        ]
        return repaired_items if repaired_items != value else value
    if not isinstance(value, dict):
        return value

    resolver_key = REFERENCE_RESOLVER_KEYS.get(_normalized_body_key(key_hint))
    if resolver_key is not None:
        resolved_id = _resolve_reference_id(resolver_key, value, task_analysis=task_analysis, history=history)
        if resolved_id not in {None, ""}:
            return {"id": resolved_id}

    repaired: dict[str, Any] = {}
    changed = False
    for key, nested_value in value.items():
        repaired_value = _repair_body_references(
            nested_value,
            task_analysis=task_analysis,
            history=history,
            key_hint=str(key),
        )
        repaired[key] = repaired_value
        changed = changed or repaired_value != nested_value

    if resolver_key is not None and repaired.get("id") not in {None, ""}:
        return {"id": repaired["id"]}
    return repaired if changed else value


def _resolve_reference_id(
    resolver_key: str,
    value: dict[str, Any],
    *,
    task_analysis: TaskAnalysis,
    history: list[dict[str, Any]],
) -> Any | None:
    if value.get("id") not in {None, ""}:
        return value["id"]
    resolver = _REFERENCE_ID_RESOLVERS.get(resolver_key)
    if resolver is None:
        return None
    return resolver(value, task_analysis, history)


def _normalized_body_key(value: str) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _mapping_value(mapping: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        if key in mapping and mapping[key] not in {None, ""}:
            return mapping[key]
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in {None, ""}:
            return value
    return None


def _normalized_text(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    text = " ".join(str(value).strip().casefold().split())
    return text or None


def _candidate_id(candidate: dict[str, Any]) -> Any | None:
    value = candidate.get("id")
    if value in {None, ""}:
        return None
    return value


def _candidate_full_name(candidate: dict[str, Any]) -> str | None:
    explicit_name = _normalized_text(candidate.get("name") or candidate.get("displayName"))
    if explicit_name:
        return explicit_name
    first_name = _normalized_text(candidate.get("firstName"))
    last_name = _normalized_text(candidate.get("lastName"))
    joined = " ".join(part for part in (first_name, last_name) if part)
    return joined or None


def _history_candidates(history: list[dict[str, Any]], *base_paths: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        if method not in {"GET", "POST", "PUT"}:
            continue
        if not any(path == base_path or path.startswith(f"{base_path}/") for base_path in base_paths):
            continue
        if isinstance(response.get("value"), dict):
            candidates.append(response["value"])
        values = response.get("values") or []
        if isinstance(values, list):
            candidates.extend(candidate for candidate in values if isinstance(candidate, dict))
    return candidates


def _resolve_customer_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_org = _mapping_value(ref, "organizationNumber", "customerOrganizationNumber")
    target_name = _mapping_value(ref, "name", "customerName")
    target_org = str(target_org) if target_org not in {None, ""} else None
    target_name = _normalized_text(target_name)
    for candidate in _history_candidates(history, "/customer"):
        if target_org and str(candidate.get("organizationNumber")) == target_org and _candidate_id(candidate) is not None:
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name")) == target_name and _candidate_id(candidate) is not None:
            return _candidate_id(candidate)
    fallback = resolved_customer_from_history(history, task_analysis)
    return _candidate_id(fallback) if isinstance(fallback, dict) else None


def _resolve_supplier_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_org = _mapping_value(ref, "organizationNumber")
    target_name = _normalized_text(_mapping_value(ref, "name", "supplierName"))
    for candidate in _history_candidates(history, "/supplier"):
        if target_org not in {None, ""} and str(candidate.get("organizationNumber")) == str(target_org):
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name")) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_employee_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_email = _normalized_text(_mapping_value(ref, "email", "employeeEmail", "projectManagerEmail"))
    target_number = _mapping_value(ref, "employeeNumber", "number")
    target_name = _normalized_text(
        _mapping_value(ref, "name")
        or " ".join(
            part
            for part in (
                str(_mapping_value(ref, "firstName") or "").strip(),
                str(_mapping_value(ref, "lastName") or "").strip(),
            )
            if part
        )
    )
    for candidate in _history_candidates(history, "/employee"):
        if target_email and _normalized_text(candidate.get("email")) == target_email:
            return _candidate_id(candidate)
        if target_number not in {None, ""} and str(candidate.get("employeeNumber") or candidate.get("number")) == str(target_number):
            return _candidate_id(candidate)
        if target_name and _candidate_full_name(candidate) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_project_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_number = _mapping_value(ref, "projectNumber", "number")
    target_name = _normalized_text(_mapping_value(ref, "name", "projectName"))
    for candidate in _history_candidates(history, "/project"):
        if target_number not in {None, ""} and str(candidate.get("projectNumber") or candidate.get("number")) == str(target_number):
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name")) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_department_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_number = _mapping_value(ref, "departmentNumber", "number")
    target_name = _normalized_text(_mapping_value(ref, "name", "departmentName"))
    for candidate in _history_candidates(history, "/department"):
        if target_number not in {None, ""} and str(candidate.get("departmentNumber") or candidate.get("number")) == str(target_number):
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name")) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_activity_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_number = _mapping_value(ref, "activityNumber", "number")
    target_name = _normalized_text(_mapping_value(ref, "name", "activityName", "displayName"))
    for candidate in _history_candidates(history, "/activity", "/project/activity"):
        if target_number not in {None, ""} and str(candidate.get("number") or candidate.get("activityNumber")) == str(target_number):
            return _candidate_id(candidate)
        candidate_name = _normalized_text(candidate.get("name") or candidate.get("displayName"))
        if target_name and candidate_name == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_product_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_number = _mapping_value(ref, "productNumber", "number")
    target_name = _normalized_text(_mapping_value(ref, "name", "description"))
    for candidate in _history_candidates(history, "/product"):
        if target_number not in {None, ""} and str(candidate.get("number") or candidate.get("productNumber")) == str(target_number):
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name") or candidate.get("description")) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_payment_type_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_description = _normalized_text(_mapping_value(ref, "description", "displayName", "name"))
    for candidate in _history_candidates(history, "/invoice/paymentType", "/travelExpense/paymentType", "/ledger/paymentTypeOut"):
        if target_description and _normalized_text(candidate.get("description") or candidate.get("displayName")) == target_description:
            return _candidate_id(candidate)
    return best_effort_payment_type_id(task_analysis, history)


def _resolve_ledger_account_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_number = _mapping_value(ref, "accountNumber", "number")
    target_name = _normalized_text(_mapping_value(ref, "name", "displayName"))
    for candidate in _history_candidates(history, "/ledger/account"):
        if target_number not in {None, ""} and str(candidate.get("number") or candidate.get("accountNumber")) == str(target_number):
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name") or candidate.get("displayName")) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_vat_type_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_code = _mapping_value(ref, "code", "number", "vatCode")
    target_name = _normalized_text(_mapping_value(ref, "name", "description", "displayName"))
    target_percentage = _safe_float(_mapping_value(ref, "percentage", "vatRate", "rate"))
    for candidate in _history_candidates(history, "/ledger/vatType"):
        if target_code not in {None, ""} and str(candidate.get("code") or candidate.get("number")) == str(target_code):
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("description") or candidate.get("displayName") or candidate.get("name")) == target_name:
            return _candidate_id(candidate)
        candidate_percentage = _safe_float(candidate.get("percentage") or candidate.get("vatRate") or candidate.get("rate"))
        if target_percentage is not None and candidate_percentage is not None and candidate_percentage == target_percentage:
            return _candidate_id(candidate)
    return None


def _safe_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_contact_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_email = _normalized_text(_mapping_value(ref, "email"))
    target_name = _normalized_text(_mapping_value(ref, "name", "displayName"))
    for candidate in _history_candidates(history, "/contact"):
        if target_email and _normalized_text(candidate.get("email")) == target_email:
            return _candidate_id(candidate)
        if target_name and _candidate_full_name(candidate) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_division_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_number = _mapping_value(ref, "number", "divisionNumber")
    target_name = _normalized_text(_mapping_value(ref, "name", "displayName"))
    for candidate in _history_candidates(history, "/division"):
        if target_number not in {None, ""} and str(candidate.get("number") or candidate.get("divisionNumber")) == str(target_number):
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name") or candidate.get("displayName")) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_currency_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_code = _normalized_text(_mapping_value(ref, "code", "currencyCode", "isoCode"))
    target_name = _normalized_text(_mapping_value(ref, "name", "displayName", "description"))
    for candidate in _history_candidates(history, "/currency"):
        candidate_code = _normalized_text(candidate.get("code") or candidate.get("currencyCode") or candidate.get("isoCode"))
        if target_code and candidate_code == target_code:
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name") or candidate.get("displayName")) == target_name:
            return _candidate_id(candidate)
    return None


def _resolve_asset_reference(ref: dict[str, Any], task_analysis: TaskAnalysis, history: list[dict[str, Any]]) -> Any | None:
    target_number = _mapping_value(ref, "number", "assetNumber")
    target_name = _normalized_text(_mapping_value(ref, "name", "displayName"))
    for candidate in _history_candidates(history, "/asset"):
        if target_number not in {None, ""} and str(candidate.get("number") or candidate.get("assetNumber")) == str(target_number):
            return _candidate_id(candidate)
        if target_name and _normalized_text(candidate.get("name") or candidate.get("displayName")) == target_name:
            return _candidate_id(candidate)
    return None


_REFERENCE_ID_RESOLVERS: dict[str, Callable[[dict[str, Any], TaskAnalysis, list[dict[str, Any]]], Any | None]] = {
    "activity": _resolve_activity_reference,
    "asset": _resolve_asset_reference,
    "contact": _resolve_contact_reference,
    "currency": _resolve_currency_reference,
    "customer": _resolve_customer_reference,
    "department": _resolve_department_reference,
    "division": _resolve_division_reference,
    "employee": _resolve_employee_reference,
    "ledger_account": _resolve_ledger_account_reference,
    "payment_type": _resolve_payment_type_reference,
    "product": _resolve_product_reference,
    "project": _resolve_project_reference,
    "supplier": _resolve_supplier_reference,
    "vat_type": _resolve_vat_type_reference,
}


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
