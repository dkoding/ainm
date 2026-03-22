from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any

from app.raw.errors import RawExecutionError
from app.semantic_contract import canonicalize_selector_value, selector_family_for_entity
from app.utils import camel_case, normalize_key


CONTROL_FIELDS = {"date_window"}
DEFAULT_SELECTOR_STRING_FIELDS = {
    "customer": "name",
    "department": "name",
    "employee": "email",
    "invoice_payment_type": "description",
    "ledger_account": "number",
    "product": "name",
    "product_unit": "name",
    "project": "name",
    "supplier": "name",
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
    selector_family = selector_family_for_entity(family)
    if isinstance(value, dict):
        return canonicalize_selector_value(selector_family, value)
    if isinstance(value, int):
        return {"id": value}
    if isinstance(value, str):
        field = DEFAULT_SELECTOR_STRING_FIELDS.get(family, "name")
        return canonicalize_selector_value(selector_family, {field: value})
    raise RawExecutionError(message=f"Unsupported selector value for {family}: {value!r}")


def id_ref(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if "id" in value:
            return {"id": coerce_int_like(value["id"], field_name="id")}
        return value
    return {"id": coerce_int_like(value, field_name="id")}


def is_int_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and value.strip().isdigit()


def coerce_int_like(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise RawExecutionError(message=f"{field_name} must be an integer id, not a boolean.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise RawExecutionError(message=f"{field_name} must be an integer id or numeric string.")


def is_iso_date_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return False
    try:
        date.fromisoformat(value.strip())
    except ValueError:
        return False
    return True


def default_date_window(current_date: str, *, days_back: int = 370, days_forward: int = 1) -> dict[str, str]:
    anchor = date.fromisoformat(current_date)
    return {
        "from": (anchor - timedelta(days=days_back)).isoformat(),
        "to": (anchor + timedelta(days=days_forward)).isoformat(),
    }


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
