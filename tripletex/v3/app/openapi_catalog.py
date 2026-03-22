from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.utils import PROJECT_ROOT, load_json


HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
OPENAPI_PATH = PROJECT_ROOT / "docs" / "openapi.json"


class OpenApiCatalog:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.operations: dict[str, dict[str, Any]] = {}
        for path, path_item in payload.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                operation_id = operation.get("operationId")
                if not operation_id:
                    continue
                self.operations[operation_id] = {
                    "path": path,
                    "path_item": path_item,
                    "method": method.lower(),
                    "operation": operation,
                }

    def input_info(self, operation_id: str, input_name: str, *, section: str | None = None) -> dict[str, Any] | None:
        operation_meta = self.operations[operation_id]
        if section in {None, "path", "query"}:
            for parameter in self._merged_parameters(operation_meta):
                if parameter.get("name") != input_name:
                    continue
                if section is not None and parameter.get("in") != section:
                    continue
                return {
                    "section": parameter.get("in"),
                    "name": parameter.get("name"),
                    "description": parameter.get("description", ""),
                    "required": bool(parameter.get("required")),
                    "schema": self._resolve_schema(parameter.get("schema")),
                }
        if section in {None, "body"}:
            body_schema = self.body_schema(operation_id)
            if input_name == "body":
                return {
                    "section": "body",
                    "name": "body",
                    "description": "",
                    "required": bool(self._request_body(operation_meta).get("required")),
                    "schema": body_schema,
                }
            properties = body_schema.get("properties", {})
            if input_name in properties:
                property_schema = properties[input_name]
                return {
                    "section": "body",
                    "name": input_name,
                    "description": property_schema.get("description", ""),
                    "required": input_name in body_schema.get("required", []),
                    "schema": property_schema,
                }
        return None

    def body_schema(self, operation_id: str) -> dict[str, Any]:
        operation_meta = self.operations[operation_id]
        request_body = self._request_body(operation_meta)
        if not request_body:
            return {}
        content = request_body.get("content", {})
        if not content:
            return {}
        preferred = ("application/json", "application/json; charset=utf-8", "multipart/form-data")
        for content_type in preferred:
            if content_type in content:
                return self._resolve_schema(content[content_type].get("schema"))
        _, first_value = next(iter(content.items()))
        return self._resolve_schema(first_value.get("schema"))

    def _request_body(self, operation_meta: dict[str, Any]) -> dict[str, Any]:
        request_body = operation_meta["operation"].get("requestBody") or {}
        if "$ref" not in request_body:
            return request_body
        current: Any = self.payload
        for part in request_body["$ref"][2:].split("/"):
            current = current[part]
        return current

    def _merged_parameters(self, operation_meta: dict[str, Any]) -> list[dict[str, Any]]:
        by_name: dict[tuple[str, str], dict[str, Any]] = {}
        for container in (
            operation_meta["path_item"].get("parameters", []),
            operation_meta["operation"].get("parameters", []),
        ):
            for parameter in container:
                if not isinstance(parameter, dict):
                    continue
                key = (parameter.get("in", ""), parameter.get("name", ""))
                by_name[key] = parameter
        return list(by_name.values())

    def _resolve_schema(self, schema: dict[str, Any] | None, *, seen_refs: frozenset[str] | None = None) -> dict[str, Any]:
        if not schema:
            return {}
        seen = seen_refs or frozenset()
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref in seen:
                return {"type": schema.get("type", "object"), "ref": ref}
            current: Any = self.payload
            for part in ref[2:].split("/"):
                current = current[part]
            resolved = self._resolve_schema(current, seen_refs=seen | {ref})
            if "ref" not in resolved:
                resolved["ref"] = ref
            return resolved

        resolved = {key: value for key, value in schema.items() if key != "allOf"}
        if "properties" in resolved:
            resolved["properties"] = {
                key: self._resolve_schema(value, seen_refs=seen)
                for key, value in resolved.get("properties", {}).items()
            }
        if "items" in resolved:
            resolved["items"] = self._resolve_schema(resolved.get("items"), seen_refs=seen)
        if "allOf" in schema:
            merged = dict(resolved)
            for item in schema["allOf"]:
                merged = self._merge_schema(merged, self._resolve_schema(item, seen_refs=seen))
            return merged
        return resolved

    def _merge_schema(self, base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in overlay.items():
            if key == "properties":
                merged.setdefault("properties", {})
                merged["properties"].update(value)
                continue
            if key == "required":
                existing = list(merged.get("required", []))
                merged["required"] = sorted({*existing, *value})
                continue
            if key == "items":
                merged["items"] = value
                continue
            if merged.get(key) is None:
                merged[key] = value
                continue
            if key not in merged:
                merged[key] = value
        return merged


@lru_cache(maxsize=1)
def load_openapi_catalog() -> OpenApiCatalog:
    return OpenApiCatalog(load_json(OPENAPI_PATH))
