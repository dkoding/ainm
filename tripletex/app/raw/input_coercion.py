from __future__ import annotations

import re
from typing import Any

from app.openapi_catalog import OpenApiCatalog, load_openapi_catalog
from app.raw.catalog import RawCatalog, load_raw_catalog
from app.runtime_refs import canonical_token_owner_employee_alias
from app.utils import normalize_key

CSV_STRING_FIELDS = {"fields", "sorting"}


class RawInputCoercer:
    def __init__(
        self,
        raw_catalog: RawCatalog | None = None,
        openapi_catalog: OpenApiCatalog | None = None,
    ) -> None:
        self.raw_catalog = raw_catalog or load_raw_catalog()
        self.openapi_catalog = openapi_catalog or load_openapi_catalog()

    def normalize_operation_inputs(self, operation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            if value is None:
                normalized[key] = value
                continue
            info = self.openapi_catalog.input_info(operation_id, key)
            if info is None:
                normalized[key] = value
                continue
            coerced = self._coerce_input_value(value, info)
            if coerced is _DROP_VALUE:
                continue
            normalized[key] = coerced
        return normalized

    def normalize_command_inputs(self, command_meta: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        operation_id = command_meta["operationId"]
        body_schema = self.openapi_catalog.body_schema(operation_id)
        body_properties = body_schema.get("properties", {})
        bindings = command_meta.get("inputBindings", {})
        for key, value in payload.items():
            if value is None:
                normalized[key] = value
                continue
            binding = bindings.get(key)
            if key in {"body", "payload"}:
                info = self.openapi_catalog.input_info(operation_id, "body", section="body")
            elif binding and binding.get("targetSection") in {"path", "query", "body"}:
                info = self.openapi_catalog.input_info(
                    operation_id,
                    binding.get("targetName", ""),
                    section=binding.get("targetSection"),
                )
            elif command_meta.get("allowsBodyPassthrough") and key in body_properties:
                info = self.openapi_catalog.input_info(operation_id, key, section="body")
            else:
                info = None
            if info is None:
                normalized[key] = value
                continue
            coerced = self._coerce_input_value(value, info)
            if coerced is _DROP_VALUE:
                continue
            normalized[key] = coerced
        return normalized

    def has_documented_default(self, operation_id: str, input_name: str, *, section: str | None = None) -> bool:
        info = self.openapi_catalog.input_info(operation_id, input_name, section=section)
        if info is None:
            return False
        schema = info.get("schema", {})
        if schema.get("default") is not None:
            return True
        description = str(info.get("description", "")).lower()
        return bool(re.search(r"\bdefaults?\b", description))

    def has_token_owner_default(self, operation_id: str, input_name: str, *, section: str | None = None) -> bool:
        info = self.openapi_catalog.input_info(operation_id, input_name, section=section)
        if info is None:
            return False
        description = str(info.get("description", "")).lower()
        return "token owner" in description

    def _coerce_input_value(self, value: Any, info: dict[str, Any]) -> Any:
        if info["section"] in {"path", "query"} and self._contains_token_owner_placeholder(value):
            if "token owner" in str(info.get("description", "")).lower():
                return _DROP_VALUE
        return self._coerce_value(
            value,
            info.get("schema", {}),
            field_name=info.get("name", ""),
            description=info.get("description", ""),
        )

    def _coerce_value(self, value: Any, schema: dict[str, Any], *, field_name: str, description: str) -> Any:
        resolved_schema = schema or {}
        schema_type = resolved_schema.get("type")
        if schema_type is None:
            if resolved_schema.get("properties"):
                schema_type = "object"
            elif resolved_schema.get("items"):
                schema_type = "array"

        if schema_type == "integer":
            return self._coerce_integer(value)
        if schema_type == "number":
            return self._coerce_number(value)
        if schema_type == "boolean":
            return self._coerce_boolean(value)
        if schema_type == "string":
            return self._coerce_string(value, field_name=field_name, description=description)
        if schema_type == "array":
            return self._coerce_array(value, resolved_schema, field_name=field_name, description=description)
        if schema_type == "object":
            return self._coerce_object(value, resolved_schema, field_name=field_name)
        return value

    def _coerce_integer(self, value: Any) -> Any:
        scalar = self._unwrap_scalar_candidate(value)
        if isinstance(scalar, bool):
            return value
        if isinstance(scalar, int):
            return scalar
        if isinstance(scalar, float) and scalar.is_integer():
            return int(scalar)
        if isinstance(scalar, str):
            stripped = scalar.strip()
            if re.fullmatch(r"[+-]?\d+", stripped):
                return int(stripped)
            if re.fullmatch(r"[+-]?\d+\.0+", stripped):
                return int(float(stripped))
        return value

    def _coerce_number(self, value: Any) -> Any:
        scalar = self._unwrap_scalar_candidate(value)
        if isinstance(scalar, bool):
            return value
        if isinstance(scalar, (int, float)):
            return scalar
        if isinstance(scalar, str):
            stripped = scalar.strip()
            if re.fullmatch(r"[+-]?\d+", stripped):
                return int(stripped)
            if re.fullmatch(r"[+-]?(?:\d+\.\d+|\d+\.\d*|\.\d+)", stripped):
                return float(stripped)
        return value

    def _coerce_boolean(self, value: Any) -> Any:
        scalar = self._unwrap_scalar_candidate(value)
        if isinstance(scalar, bool):
            return scalar
        if isinstance(scalar, int) and scalar in {0, 1}:
            return bool(scalar)
        if isinstance(scalar, str):
            lowered = scalar.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return value

    def _coerce_string(self, value: Any, *, field_name: str, description: str) -> Any:
        if self._is_csv_string_field(field_name, description):
            joined = self._coerce_csv_string(value, field_name=field_name, description=description)
            if joined is not None:
                return joined
        scalar = self._unwrap_scalar_candidate(value)
        if isinstance(scalar, str):
            return scalar
        if isinstance(scalar, (int, float)) and not isinstance(scalar, bool):
            return str(scalar)
        return value

    def _coerce_array(self, value: Any, schema: dict[str, Any], *, field_name: str, description: str) -> Any:
        items_schema = schema.get("items", {})
        items = value
        if isinstance(value, dict) and isinstance(value.get("values"), list):
            items = value["values"]
        if not isinstance(items, list):
            return value
        return [
            self._coerce_value(item, items_schema, field_name=field_name, description=description)
            for item in items
        ]

    def _coerce_object(self, value: Any, schema: dict[str, Any], *, field_name: str) -> Any:
        if not isinstance(value, dict):
            if self._looks_like_id_ref_schema(schema):
                coerced = self._coerce_integer(value)
                if isinstance(coerced, int):
                    return {"id": coerced}
            return value
        properties = schema.get("properties", {})
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            property_schema = properties.get(key, {})
            normalized[key] = self._coerce_value(
                item,
                property_schema,
                field_name=key,
                description=property_schema.get("description", ""),
            )
        return normalized

    def _coerce_csv_string(self, value: Any, *, field_name: str, description: str) -> str | None:
        items = value
        if isinstance(value, dict) and isinstance(value.get("values"), list):
            items = value["values"]
        if not isinstance(items, list):
            return None
        is_id_list = normalize_key(field_name).endswith("ids") or "list of ids" in description.lower()
        rendered: list[str] = []
        for item in items:
            scalar = self._unwrap_scalar_candidate(item)
            if is_id_list:
                coerced = self._coerce_integer(scalar)
                if isinstance(coerced, int):
                    rendered.append(str(coerced))
                    continue
            if isinstance(scalar, str):
                rendered.append(scalar)
                continue
            if isinstance(scalar, (int, float)) and not isinstance(scalar, bool):
                rendered.append(str(scalar))
        if not rendered:
            return ""
        return ",".join(rendered)

    def _unwrap_scalar_candidate(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "id" in value:
            return value["id"]
        if set(value.keys()) == {"value"}:
            return value["value"]
        values = value.get("values")
        if isinstance(values, list) and len(values) == 1:
            return values[0]
        return value

    def _looks_like_id_ref_schema(self, schema: dict[str, Any]) -> bool:
        properties = schema.get("properties", {})
        id_schema = properties.get("id")
        if not isinstance(id_schema, dict):
            return False
        return id_schema.get("type") == "integer"

    def _contains_token_owner_placeholder(self, value: Any) -> bool:
        if canonical_token_owner_employee_alias(value) is not None:
            return True
        if isinstance(value, dict):
            if canonical_token_owner_employee_alias(value.get("id")) is not None:
                return True
            if set(value.keys()) == {"value"}:
                return self._contains_token_owner_placeholder(value["value"])
            values = value.get("values")
            if isinstance(values, list) and len(values) == 1:
                return self._contains_token_owner_placeholder(values[0])
            return False
        if isinstance(value, list) and len(value) == 1:
            return self._contains_token_owner_placeholder(value[0])
        return False

    def _is_csv_string_field(self, field_name: str, description: str) -> bool:
        normalized = normalize_key(field_name)
        return (
            normalized in CSV_STRING_FIELDS
            or normalized.endswith("ids")
            or normalized.endswith("list")
            or "list of" in description.lower()
        )


_DROP_VALUE = object()
