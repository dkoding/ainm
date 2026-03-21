from __future__ import annotations

from typing import Any

from app.raw.errors import RawExecutionError
from app.utils import camel_case, normalize_key


CONTROL_FIELDS = {"fields", "from", "count", "sorting", "date_window"}
DEFAULT_SELECTOR_STRING_FIELDS = {
    "customer": "name",
    "department": "name",
    "employee": "email",
    "invoice_payment_type": "description",
    "ledger_account": "number",
    "product": "name",
    "product_unit": "name",
    "project": "name",
    "supplier_invoice": "invoice_number",
    "travel_cost_category": "description",
    "travel_payment_type": "description",
    "travel_rate_category": "name",
    "travel_zone": "code",
    "vat_type": "number",
    "voucher": "number",
    "voucher_type": "name",
}


def match_name(source: str, candidates: list[str]) -> str | None:
    if source in candidates:
        return source
    source_normalized = normalize_key(source)
    for candidate in candidates:
        if normalize_key(candidate) == source_normalized:
            return candidate
    if source == "name":
        name_candidates = [candidate for candidate in candidates if candidate.endswith("Name")]
        if len(name_candidates) == 1:
            return name_candidates[0]
    return None


def choose_date_window_pair(candidates: list[str]) -> tuple[str, str] | None:
    lower = {candidate.lower(): candidate for candidate in candidates}
    for candidate in candidates:
        if candidate.endswith("From"):
            twin = candidate[:-4] + "To"
            if twin in candidates:
                return candidate, twin
        if candidate.endswith("DateFrom"):
            twin = candidate[:-4] + "To"
            if twin in candidates:
                return candidate, twin
    if "datefrom" in lower and "dateto" in lower:
        return lower["datefrom"], lower["dateto"]
    return None


def extract_values(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        if "values" in payload and isinstance(payload["values"], list):
            return payload["values"]
        if "value" in payload:
            return [payload["value"]]
    if isinstance(payload, list):
        return payload
    return [payload]


def ensure_single_result(payload: Any, *, family: str, selector: Any) -> dict[str, Any]:
    values = extract_values(payload)
    if not values:
        raise RawExecutionError(message=f"No {family} matched selector {selector!r}.")
    if len(values) > 1:
        raise RawExecutionError(message=f"Selector {selector!r} matched multiple {family} records.")
    value = values[0]
    if not isinstance(value, dict):
        raise RawExecutionError(message=f"Expected object payload while resolving {family}, got {type(value).__name__}.")
    return value


def to_selector_dict(family: str, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, int):
        return {"id": value}
    if isinstance(value, str):
        field = DEFAULT_SELECTOR_STRING_FIELDS.get(family, "name")
        return {field: value}
    raise RawExecutionError(message=f"Unsupported selector value for {family}: {value!r}")


def id_ref(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if "id" in value:
            return {"id": value["id"]}
        return value
    return {"id": value}


def merge_maps(*maps: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in maps:
        for key, value in item.items():
            if value is not None:
                merged[key] = value
    return merged


def flatten_special_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    result = dict(inputs)
    for key in ("patch", "payment_spec", "send_options"):
        value = result.pop(key, None)
        if isinstance(value, dict):
            result.update(value)
    return result


def maybe_alias_ref_key(key: str) -> tuple[str, bool]:
    if key.endswith("_ref"):
        return key[:-4], True
    return key, False


def to_camel_candidates(key: str) -> list[str]:
    base, _ = maybe_alias_ref_key(key)
    camel = camel_case(base)
    return [base, camel, f"{camel}Id", f"{camel}Ids"]
