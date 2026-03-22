from __future__ import annotations

from datetime import date
import re
from typing import Any

from app.openapi_catalog import load_openapi_catalog
from app.raw.errors import RawExecutionError
from app.runtime_refs import canonical_step_output_reference


def is_int_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and value.strip().isdigit()


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


def request_body_schema(raw_meta: dict[str, Any]) -> dict[str, Any]:
    operation_id = raw_meta.get("operationId")
    if operation_id:
        return load_openapi_catalog().body_schema(operation_id)
    return next(iter(raw_meta.get("requestBody", {}).get("content", {}).values()), {})


def validate_request_body_value(
    value: Any,
    *,
    raw_meta: dict[str, Any],
    field_name: str,
    operation_id: str,
    body_label: str,
) -> None:
    body_schema = request_body_schema(raw_meta)
    schema_type = body_schema.get("type")
    if schema_type == "array":
        if not isinstance(value, list):
            raise RawExecutionError(message=f"{field_name} must be a list body for this operation.")
        for index, item in enumerate(value, start=1):
            validate_request_body_schema_value(
                item,
                schema=body_schema.get("items", {}),
                field_name=f"{field_name}[{index}]",
                operation_id=operation_id,
                body_label=body_label,
            )
        return
    if not isinstance(value, dict):
        raise RawExecutionError(message=f"{field_name} must be an object body for this operation.")
    validate_request_body_schema_value(
        value,
        schema=body_schema,
        field_name=field_name,
        operation_id=operation_id,
        body_label=body_label,
    )


def validate_request_body_schema_value(
    value: Any,
    *,
    schema: dict[str, Any],
    field_name: str,
    operation_id: str,
    body_label: str,
) -> None:
    step_reference = canonical_step_output_reference(value)
    if step_reference is not None:
        raise RawExecutionError(
            message=(
                f"{field_name} may not reference prior step outputs via {step_reference!r}. "
                "The runtime does not dereference step-output placeholders inside request bodies."
            )
        )
    schema_type = schema.get("type")
    if schema_type is None:
        if schema.get("properties"):
            schema_type = "object"
        elif schema.get("items"):
            schema_type = "array"

    leaf_name = field_name.rsplit(".", 1)[-1].split("[", 1)[0]
    if leaf_name.endswith("_date") or leaf_name in {"date", "startDate", "endDate"} or schema.get("format") == "date":
        if not is_iso_date_string(value):
            raise RawExecutionError(message=f"{field_name} must be an ISO date string YYYY-MM-DD.")
        return
    if schema_type == "integer":
        if not is_int_like(value):
            raise RawExecutionError(message=f"{field_name} must be an integer.")
        return
    if schema_type == "number":
        if not isinstance(value, (int, float)):
            raise RawExecutionError(message=f"{field_name} must be numeric.")
        return
    if schema_type == "boolean":
        if not isinstance(value, bool):
            raise RawExecutionError(message=f"{field_name} must be a boolean.")
        return
    if schema_type == "string":
        if not isinstance(value, str):
            raise RawExecutionError(message=f"{field_name} must be a string.")
        return
    if schema_type == "array":
        if not isinstance(value, list):
            raise RawExecutionError(message=f"{field_name} must be a list.")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value, start=1):
            validate_request_body_schema_value(
                item,
                schema=item_schema,
                field_name=f"{field_name}[{index}]",
                operation_id=operation_id,
                body_label=body_label,
            )
        return
    if schema_type != "object":
        return
    if not isinstance(value, dict):
        raise RawExecutionError(message=f"{field_name} must be an object.")
    properties = schema.get("properties", {})
    if properties:
        writable_properties = {
            key
            for key, item in properties.items()
            if not isinstance(item, dict) or not item.get("readOnly")
        }
        illegal = sorted(key for key, item in value.items() if item is not None and key not in writable_properties)
        if illegal:
            raise RawExecutionError(
                message=(
                    f"{body_label} for {operation_id} contains undeclared properties at {field_name}: "
                    f"{', '.join(illegal)}. Wrapper-generated, raw, and passthrough bodies must use only "
                    "OpenAPI-declared writable fields."
                )
            )
        for key, item in value.items():
            if item is None:
                continue
            validate_request_body_schema_value(
                item,
                schema=properties.get(key, {}),
                field_name=f"{field_name}.{key}",
                operation_id=operation_id,
                body_label=body_label,
            )
        return
    if "id" in value:
        step_reference = canonical_step_output_reference(value["id"])
        if step_reference is not None:
            raise RawExecutionError(
                message=(
                    f"{field_name}.id may not reference prior step outputs via {step_reference!r}. "
                    "The runtime does not dereference step-output placeholders inside request bodies."
                )
            )
    if "id" in value and not is_int_like(value["id"]):
        raise RawExecutionError(message=f"{field_name}.id must be an integer id.")
