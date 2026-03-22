from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.utils import camel_case, normalize_key


SELECTOR_FAMILIES: dict[str, dict[str, Any]] = {
    "currency_selector": {
        "allowedFields": ["id", "code", "description", "name"],
    },
    "employee_selector": {
        "allowedFields": ["id", "email", "employee_number", "first_name", "last_name", "department_id"],
        "personLike": True,
    },
    "customer_selector": {
        "allowedFields": ["id", "organization_number", "customer_account_number", "email", "invoice_email", "name"],
    },
    "supplier_selector": {
        "allowedFields": ["id", "organization_number", "email", "invoice_email", "name"],
    },
    "product_selector": {
        "allowedFields": ["id", "number", "product_number", "name", "ean"],
    },
    "order_selector": {
        "allowedFields": ["id", "number", "customer_id", "date_window"],
    },
    "invoice_selector": {
        "allowedFields": ["id", "invoice_number", "customer_id", "voucher_id", "kid", "date_window"],
    },
    "supplier_invoice_selector": {
        "allowedFields": ["id", "invoice_number", "supplier_id", "voucher_id", "kid", "date_window"],
    },
    "travel_expense_selector": {
        "allowedFields": ["id", "employee_id", "project_id", "department_id", "state", "departure_date_from", "return_date_to"],
    },
    "project_selector": {
        "allowedFields": ["id", "name", "number", "customer_id", "project_manager_id", "department_id"],
    },
    "department_selector": {
        "allowedFields": ["id", "name", "department_number", "department_manager_id"],
    },
    "invoice_payment_type_selector": {
        "allowedFields": ["id", "description", "query"],
    },
    "ledger_account_selector": {
        "allowedFields": ["id", "number", "description", "name"],
    },
    "voucher_selector": {
        "allowedFields": ["id", "number", "type_id", "date_window"],
    },
    "voucher_type_selector": {
        "allowedFields": ["id", "name"],
    },
    "product_unit_selector": {
        "allowedFields": ["id", "name"],
    },
    "travel_cost_category_selector": {
        "allowedFields": ["id", "description", "category"],
    },
    "travel_payment_type_selector": {
        "allowedFields": ["id", "description", "query", "show_on_employee_expenses", "is_inactive"],
    },
    "travel_rate_selector": {
        "allowedFields": ["id", "name", "description"],
    },
    "travel_rate_category_selector": {
        "allowedFields": ["id", "name"],
    },
    "travel_zone_selector": {
        "allowedFields": ["id", "code", "name", "location"],
    },
    "vat_type_selector": {
        "allowedFields": ["id", "number", "type_of_vat", "vat_date"],
    },
}

PAYLOAD_FAMILIES: dict[str, dict[str, Any]] = {
    "line_item": {
        "allowedFields": [
            "product_ref",
            "description",
            "count",
            "unit_price_ex_vat",
            "unit_price_inc_vat",
            "vat_type_ref",
            "currency_ref",
        ],
        "requiredFields": ["description", "count"],
        "referenceFamilies": {
            "product_ref": "product",
            "vat_type_ref": "vat_type",
            "currency_ref": "currency",
        },
        "rawFieldMap": {
            "product_ref": "product",
            "description": "description",
            "count": "count",
            "unit_price_ex_vat": "unitPriceExcludingVatCurrency",
            "unit_price_inc_vat": "unitPriceIncludingVatCurrency",
            "vat_type_ref": "vatType",
            "currency_ref": "currency",
        },
    },
    "payment_spec": {
        "allowedFields": ["payment_date", "payment_type_ref", "paid_amount", "paid_amount_currency"],
        "requiredFields": ["payment_date", "payment_type_ref", "paid_amount"],
        "referenceFamilies": {
            "payment_type_ref": "invoice_payment_type",
        },
        "rawFieldMap": {
            "payment_date": "paymentDate",
            "payment_type_ref": "paymentTypeRef",
            "paid_amount": "paidAmount",
            "paid_amount_currency": "paidAmountCurrency",
        },
    },
    "posting_line": {
        "allowedFields": [
            "account_ref",
            "amount",
            "amount_currency",
            "currency_ref",
            "date",
            "description",
            "vat_type_ref",
            "customer_ref",
            "supplier_ref",
            "employee_ref",
            "project_ref",
            "department_ref",
        ],
        "requiredFields": ["account_ref", "amount", "date"],
        "referenceFamilies": {
            "account_ref": "ledger_account",
            "vat_type_ref": "vat_type",
            "currency_ref": "currency",
            "customer_ref": "customer",
            "supplier_ref": "supplier",
            "employee_ref": "employee",
            "project_ref": "project",
            "department_ref": "department",
        },
        "rawFieldMap": {
            "account_ref": "account",
            "amount": "amount",
            "amount_currency": "amountCurrency",
            "currency_ref": "currency",
            "date": "date",
            "description": "description",
            "vat_type_ref": "vatType",
            "customer_ref": "customer",
            "supplier_ref": "supplier",
            "employee_ref": "employee",
            "project_ref": "project",
            "department_ref": "department",
        },
    },
    "travel_details": {
        "allowedFields": [
            "departure_date",
            "return_date",
            "departure_time",
            "return_time",
            "departure_from",
            "destination",
            "purpose",
            "is_foreign_travel",
            "is_day_trip",
            "is_compensation_from_rates",
            "detailed_journey_description",
        ],
        "requiredFields": ["departure_date", "return_date", "destination"],
        "rawFieldMap": {
            "departure_date": "departureDate",
            "return_date": "returnDate",
            "departure_time": "departureTime",
            "return_time": "returnTime",
            "departure_from": "departureFrom",
            "destination": "destination",
            "purpose": "purpose",
            "is_foreign_travel": "isForeignTravel",
            "is_day_trip": "isDayTrip",
            "is_compensation_from_rates": "isCompensationFromRates",
            "detailed_journey_description": "detailedJourneyDescription",
        },
    },
    "travel_expense_cost_row": {
        "allowedFields": [
            "cost_category_ref",
            "payment_type_ref",
            "date",
            "comments",
            "amount_currency_inc_vat",
            "vat_type_ref",
            "is_chargeable",
        ],
        "requiredFields": ["cost_category_ref", "date", "amount_currency_inc_vat"],
        "referenceFamilies": {
            "cost_category_ref": "travel_cost_category",
            "payment_type_ref": "travel_payment_type",
            "vat_type_ref": "vat_type",
        },
        "rawFieldMap": {
            "cost_category_ref": "costCategory",
            "payment_type_ref": "paymentType",
            "date": "date",
            "comments": "comments",
            "amount_currency_inc_vat": "amountCurrencyIncVat",
            "vat_type_ref": "vatType",
            "is_chargeable": "isChargeable",
        },
    },
    "travel_expense_mileage_row": {
        "allowedFields": [
            "rate_type_ref",
            "rate_category_ref",
            "date",
            "departure_location",
            "destination",
            "km",
            "is_company_car",
        ],
        "requiredFields": ["rate_type_ref", "rate_category_ref", "date", "departure_location", "destination", "km"],
        "referenceFamilies": {
            "rate_type_ref": "travel_rate",
            "rate_category_ref": "travel_rate_category",
        },
        "rawFieldMap": {
            "rate_type_ref": "rateType",
            "rate_category_ref": "rateCategory",
            "date": "date",
            "departure_location": "departureLocation",
            "destination": "destination",
            "km": "km",
            "is_company_car": "isCompanyCar",
        },
    },
    "travel_expense_per_diem_row": {
        "allowedFields": [
            "rate_type_ref",
            "rate_category_ref",
            "country_code",
            "travel_expense_zone_id",
            "overnight_accommodation",
            "location",
            "address",
            "count",
            "is_deduction_for_breakfast",
            "is_deduction_for_lunch",
            "is_deduction_for_dinner",
        ],
        "requiredFields": ["rate_type_ref", "rate_category_ref", "location", "count"],
        "referenceFamilies": {
            "rate_type_ref": "travel_rate",
            "rate_category_ref": "travel_rate_category",
        },
        "rawFieldMap": {
            "rate_type_ref": "rateType",
            "rate_category_ref": "rateCategory",
            "country_code": "countryCode",
            "travel_expense_zone_id": "travelExpenseZoneId",
            "overnight_accommodation": "overnightAccommodation",
            "location": "location",
            "address": "address",
            "count": "count",
            "is_deduction_for_breakfast": "isDeductionForBreakfast",
            "is_deduction_for_lunch": "isDeductionForLunch",
            "is_deduction_for_dinner": "isDeductionForDinner",
        },
    },
    "travel_expense_accommodation_row": {
        "allowedFields": ["rate_type_ref", "rate_category_ref", "zone", "location", "address", "count"],
        "requiredFields": ["rate_type_ref", "rate_category_ref", "location", "count"],
        "referenceFamilies": {
            "rate_type_ref": "travel_rate",
            "rate_category_ref": "travel_rate_category",
        },
        "rawFieldMap": {
            "rate_type_ref": "rateType",
            "rate_category_ref": "rateCategory",
            "zone": "zone",
            "location": "location",
            "address": "address",
            "count": "count",
        },
    },
}

ENTITY_SELECTOR_FAMILIES = {
    "currency": "currency_selector",
    "currency_selector": "currency_selector",
    "customer": "customer_selector",
    "customer_selector": "customer_selector",
    "department": "department_selector",
    "department_manager": "employee_selector",
    "department_selector": "department_selector",
    "employee": "employee_selector",
    "employee_selector": "employee_selector",
    "invoice_payment_type": "invoice_payment_type_selector",
    "invoice_payment_type_selector": "invoice_payment_type_selector",
    "invoice_selector": "invoice_selector",
    "ledger_account": "ledger_account_selector",
    "ledger_account_selector": "ledger_account_selector",
    "project": "project_selector",
    "project_manager": "employee_selector",
    "project_selector": "project_selector",
    "product_unit": "product_unit_selector",
    "product_unit_selector": "product_unit_selector",
    "supplier": "supplier_selector",
    "supplier_invoice_selector": "supplier_invoice_selector",
    "travel_cost_category": "travel_cost_category_selector",
    "travel_cost_category_selector": "travel_cost_category_selector",
    "travel_expense_selector": "travel_expense_selector",
    "travel_payment_type": "travel_payment_type_selector",
    "travel_payment_type_selector": "travel_payment_type_selector",
    "travel_rate": "travel_rate_selector",
    "travel_rate_selector": "travel_rate_selector",
    "travel_rate_category": "travel_rate_category_selector",
    "travel_rate_category_selector": "travel_rate_category_selector",
    "travel_zone": "travel_zone_selector",
    "travel_zone_selector": "travel_zone_selector",
    "vat_type": "vat_type_selector",
    "vat_type_selector": "vat_type_selector",
    "voucher": "voucher_selector",
    "voucher_selector": "voucher_selector",
    "voucher_type": "voucher_type_selector",
}

FLOW_INPUT_SEMANTICS_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("invoice.order_first", "line_items"): {"kind": "array_payload", "itemFamily": "line_item"},
    ("invoice.direct", "invoiceable_lines"): {"kind": "array_payload", "itemFamily": "line_item"},
    ("invoice.direct", "payment_spec"): {"kind": "payload", "payloadFamily": "payment_spec"},
    ("invoice.register_payment", "payment_spec"): {"kind": "payload", "payloadFamily": "payment_spec"},
    ("project.create_for_customer", "customer"): {
        "kind": "selector_or_create_payload",
        "selectorFamily": "customer_selector",
        "createCommandName": "customer.create",
    },
    ("project.create_for_customer", "project_manager"): {"kind": "selector", "selectorFamily": "employee_selector"},
    ("project.create_for_customer", "department"): {"kind": "selector", "selectorFamily": "department_selector"},
    ("supplier_invoice.import_from_attachment", "postings"): {"kind": "array_payload", "itemFamily": "posting_line"},
    ("travel_expense.create_basic", "department"): {"kind": "selector", "selectorFamily": "department_selector"},
    ("travel_expense.create_basic", "employee"): {"kind": "selector", "selectorFamily": "employee_selector"},
    ("travel_expense.create_basic", "project"): {"kind": "selector", "selectorFamily": "project_selector"},
    ("travel_expense.create_basic", "travel_details"): {"kind": "payload", "payloadFamily": "travel_details"},
    ("travel_expense.create_with_rows", "accommodation_rows"): {
        "kind": "array_payload",
        "itemFamily": "travel_expense_accommodation_row",
    },
    ("travel_expense.create_with_rows", "cost_rows"): {"kind": "array_payload", "itemFamily": "travel_expense_cost_row"},
    ("travel_expense.create_with_rows", "department"): {"kind": "selector", "selectorFamily": "department_selector"},
    ("travel_expense.create_with_rows", "employee"): {"kind": "selector", "selectorFamily": "employee_selector"},
    ("travel_expense.create_with_rows", "mileage_rows"): {
        "kind": "array_payload",
        "itemFamily": "travel_expense_mileage_row",
    },
    ("travel_expense.create_with_rows", "per_diem_rows"): {
        "kind": "array_payload",
        "itemFamily": "travel_expense_per_diem_row",
    },
    ("travel_expense.create_with_rows", "project"): {"kind": "selector", "selectorFamily": "project_selector"},
    ("travel_expense.create_with_rows", "travel_details"): {"kind": "payload", "payloadFamily": "travel_details"},
    ("voucher.manual_adjustment", "postings"): {"kind": "array_payload", "itemFamily": "posting_line"},
    ("voucher.reverse_or_correct", "correction_postings"): {"kind": "array_payload", "itemFamily": "posting_line"},
}

COMMAND_INPUT_FAMILIES: dict[tuple[str, str], dict[str, Any]] = {
    ("order.create", "order_lines"): {"kind": "array_payload", "itemFamily": "line_item"},
    ("travel_expense.create", "costs"): {"kind": "array_payload", "itemFamily": "travel_expense_cost_row"},
    ("travel_expense.create", "per_diem_compensations"): {"kind": "array_payload", "itemFamily": "travel_expense_per_diem_row"},
    ("travel_expense.create", "travel_details"): {"kind": "payload", "payloadFamily": "travel_details"},
    ("voucher.create", "postings"): {"kind": "array_payload", "itemFamily": "posting_line"},
}


def clean_contract_name(value: str) -> str:
    return value.replace("[]", "").rstrip("?").strip()


def copy_selector_families() -> dict[str, Any]:
    return deepcopy(SELECTOR_FAMILIES)


def copy_payload_families() -> dict[str, Any]:
    return deepcopy(PAYLOAD_FAMILIES)


def selector_family_for_entity(entity: str) -> str | None:
    return ENTITY_SELECTOR_FAMILIES.get(clean_contract_name(entity))


def payload_reference_family(family: str | None, field_name: str) -> str | None:
    if family is None:
        return None
    meta = PAYLOAD_FAMILIES.get(family, {})
    reference_families = meta.get("referenceFamilies", {})
    return reference_families.get(clean_contract_name(field_name))


def payload_reference_selector_family(family: str | None, field_name: str) -> str | None:
    entity_family = payload_reference_family(family, field_name)
    if entity_family is None:
        return None
    return selector_family_for_entity(entity_family)


def selector_family_for_command(command_name: str) -> str | None:
    if command_name in {"employee.search", "customer.search", "supplier.search", "project.search", "department.search"}:
        return selector_family_for_entity(command_name.split(".", 1)[0])
    return None


def flow_input_semantics(flow_name: str, input_name: str) -> dict[str, Any]:
    cleaned = clean_contract_name(input_name)
    override = FLOW_INPUT_SEMANTICS_OVERRIDES.get((flow_name, cleaned))
    if override is not None:
        return dict(override)
    selector_family = selector_family_for_entity(cleaned)
    if cleaned in {"customer", "supplier"} and selector_family:
        return {"kind": "selector_or_create_payload", "selectorFamily": selector_family}
    if selector_family:
        return {"kind": "selector", "selectorFamily": selector_family}
    return {"kind": "scalar"}


def command_input_semantics(command_name: str, input_name: str) -> dict[str, Any]:
    cleaned = clean_contract_name(input_name)
    override = COMMAND_INPUT_FAMILIES.get((command_name, cleaned))
    if override is not None:
        return dict(override)
    selector_family = selector_family_for_command(command_name)
    if selector_family and cleaned in SELECTOR_FAMILIES.get(selector_family, {}).get("allowedFields", []):
        return {"kind": "selector_field", "selectorFamily": selector_family}
    if cleaned.endswith("_ref"):
        return {"kind": "reference"}
    return {"kind": "scalar"}


def canonicalize_selector_value(selector_family: str | None, value: Any) -> Any:
    if selector_family is None or not isinstance(value, dict):
        return value
    family_meta = SELECTOR_FAMILIES.get(selector_family, {})
    allowed_fields = family_meta.get("allowedFields", [])
    allowed_lookup = {normalize_key(field): field for field in allowed_fields}
    alias_lookup = _selector_aliases(selector_family)
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = normalize_key(str(key))
        if normalized in allowed_lookup:
            result[allowed_lookup[normalized]] = item
            continue
        alias = alias_lookup.get(normalized)
        if alias == "__person_name__":
            if isinstance(item, str):
                stripped = item.strip()
                if "@" in stripped and "email" in allowed_fields:
                    result["email"] = stripped
                    continue
                first_name, last_name = split_person_name(stripped)
                if first_name:
                    result["first_name"] = first_name
                if last_name:
                    result["last_name"] = last_name
                if first_name or last_name:
                    continue
        if alias:
            result[alias] = item
            continue
        result[key] = item
    return _canonicalize_selector_id(result)


def canonicalize_payload_value(family: str | None, value: Any) -> Any:
    if family is None:
        return value
    if isinstance(value, list):
        return [canonicalize_payload_value(family, item) for item in value]
    if not isinstance(value, dict):
        return value
    meta = PAYLOAD_FAMILIES.get(family, {})
    allowed_lookup = {normalize_key(field): field for field in meta.get("allowedFields", [])}
    if not allowed_lookup:
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        canonical = allowed_lookup.get(normalize_key(str(key)), key)
        selector_family = payload_reference_selector_family(family, canonical)
        if selector_family is not None:
            result[canonical] = canonicalize_selector_value(selector_family, item)
            continue
        result[canonical] = item
    return result


def to_raw_payload_value(family: str | None, value: Any) -> Any:
    if family is None:
        return value
    if isinstance(value, list):
        return [to_raw_payload_value(family, item) for item in value]
    if not isinstance(value, dict):
        return value
    canonical = canonicalize_payload_value(family, value)
    meta = PAYLOAD_FAMILIES.get(family, {})
    raw_field_map = meta.get("rawFieldMap", {})
    result: dict[str, Any] = {}
    for key, item in canonical.items():
        target_key = raw_field_map.get(key, camel_case(key))
        if key.endswith("_ref"):
            result[target_key] = _to_ref_object(item)
        else:
            result[target_key] = item
    return result


def split_person_name(value: str) -> tuple[str, str]:
    parts = [part for part in value.split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _canonicalize_selector_id(value: dict[str, Any]) -> dict[str, Any]:
    if "id" not in value:
        return value
    normalized = dict(value)
    selector_id = normalized.get("id")
    if _is_int_like(selector_id):
        normalized["id"] = int(str(selector_id).strip()) if isinstance(selector_id, str) else selector_id
        return normalized
    if any(_has_meaningful_selector_value(item) for key, item in normalized.items() if key != "id"):
        normalized.pop("id", None)
    return normalized


def _is_int_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and value.strip().isdigit()


def _has_meaningful_selector_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _selector_aliases(selector_family: str) -> dict[str, str]:
    aliases: dict[str, str] = {
        "employee_selector": {
            "name": "__person_name__",
            "fullname": "__person_name__",
            "employeeid": "id",
            "employeenumber": "employee_number",
        },
        "project_selector": {
            "projectmanager": "project_manager_id",
        },
        "department_selector": {
            "manager": "department_manager_id",
        },
        "customer_selector": {
            "customerid": "id",
            "organizationnumber": "organization_number",
        },
        "supplier_selector": {
            "supplierid": "id",
            "organizationnumber": "organization_number",
        },
        "invoice_selector": {
            "number": "invoice_number",
        },
        "supplier_invoice_selector": {
            "number": "invoice_number",
        },
        "voucher_selector": {
            "voucherid": "id",
        },
    }.get(selector_family, {})
    return dict(aliases)


def _to_ref_object(value: Any) -> Any:
    if isinstance(value, dict):
        if "id" in value and isinstance(value["id"], str) and value["id"].strip().isdigit():
            return {"id": int(value["id"].strip())}
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return {"id": int(value.strip())}
    if isinstance(value, int):
        return {"id": value}
    return value
