from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .openapi_registry import _resource_prefixes
from .tasking import TripletexCommand


class GeneratedMethodError(RuntimeError):
    pass


@dataclass(frozen=True)
class MethodArgumentSpec:
    name: str
    location: str
    required: bool
    schema_type: str | None = None
    description: str = ""


@dataclass(frozen=True)
class GeneratedMethodSpec:
    method_name: str
    operation_id: str
    http_method: str
    template_path: str
    summary: str
    tags: tuple[str, ...]
    target_resource: str
    path_arguments: tuple[MethodArgumentSpec, ...]
    query_arguments: tuple[MethodArgumentSpec, ...]
    body_arguments: tuple[MethodArgumentSpec, ...]
    request_body_style: str
    request_body_required: bool

    @property
    def arguments(self) -> tuple[MethodArgumentSpec, ...]:
        return self.path_arguments + self.query_arguments + self.body_arguments

    def planner_hint(self) -> dict[str, Any]:
        required_arguments = [argument.name for argument in self.arguments if argument.required]
        optional_arguments = [argument.name for argument in self.arguments if not argument.required]
        return {
            "method_name": self.method_name,
            "operation_id": self.operation_id,
            "http_method": self.http_method,
            "path": self.template_path,
            "summary": self.summary,
            "required_arguments": required_arguments,
            "optional_arguments": optional_arguments,
            "argument_locations": {
                argument.name: argument.location for argument in self.arguments
            },
        }

    def build_command(self, *, arguments: dict[str, Any], reason: str) -> TripletexCommand:
        normalized_arguments = dict(arguments or {})
        allowed_arguments = {argument.name for argument in self.arguments}
        unknown_arguments = sorted(set(normalized_arguments) - allowed_arguments)
        if unknown_arguments:
            raise GeneratedMethodError(
                f"Unsupported arguments for {self.method_name}: {', '.join(unknown_arguments)}"
            )

        missing_required: list[str] = []
        for argument in self.path_arguments + self.query_arguments:
            if argument.required and _is_blank(normalized_arguments.get(argument.name)):
                missing_required.append(argument.name)

        body_values = {
            argument.name: normalized_arguments.get(argument.name)
            for argument in self.body_arguments
            if argument.name in normalized_arguments
        }
        body_present = any(not _is_blank(value) for value in body_values.values())
        if self.request_body_required or body_present:
            for argument in self.body_arguments:
                if argument.required and _is_blank(normalized_arguments.get(argument.name)):
                    missing_required.append(argument.name)

        if missing_required:
            raise GeneratedMethodError(
                f"Missing required arguments for {self.method_name}: {', '.join(sorted(set(missing_required)))}"
            )

        path = self.template_path
        for argument in self.path_arguments:
            value = normalized_arguments.get(argument.name)
            if _is_blank(value):
                continue
            path = path.replace(f"{{{argument.name}}}", quote(str(value), safe=""))

        params = {
            argument.name: normalized_arguments[argument.name]
            for argument in self.query_arguments
            if argument.name in normalized_arguments and not _is_blank(normalized_arguments[argument.name])
        }

        json_body: Any | None = None
        if self.request_body_style == "object":
            object_body = {
                argument.name: normalized_arguments[argument.name]
                for argument in self.body_arguments
                if argument.name in normalized_arguments and not _is_blank(normalized_arguments[argument.name])
            }
            if object_body or self.request_body_required:
                json_body = object_body
        elif self.request_body_style == "raw":
            raw_body = normalized_arguments.get("body")
            if not _is_blank(raw_body) or self.request_body_required:
                json_body = raw_body

        return TripletexCommand(
            method=self.http_method,
            path=path,
            reason=reason,
            params=params or None,
            json_body=json_body,
        )


class GeneratedAPIMethodRegistry:
    def __init__(self, methods: list[GeneratedMethodSpec]):
        self.methods = methods
        self._methods_by_name = {method.method_name: method for method in methods}

    @classmethod
    def from_default_spec(cls) -> "GeneratedAPIMethodRegistry":
        return _load_generated_method_registry()

    def get(self, method_name: str) -> GeneratedMethodSpec | None:
        return self._methods_by_name.get(method_name)

    def planner_hints(
        self,
        *,
        target_resource: str | None = None,
        prefixes: tuple[str, ...] | None = None,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        selected_prefixes = prefixes or _resource_prefixes(target_resource)
        selected: list[dict[str, Any]] = []
        if selected_prefixes:
            for prefix in selected_prefixes:
                for method in self.methods:
                    if not method.template_path.startswith(prefix):
                        continue
                    hint = method.planner_hint()
                    if hint in selected:
                        continue
                    selected.append(hint)
                    if len(selected) >= limit:
                        break
                if len(selected) >= limit:
                    break
        if selected:
            return selected
        return [method.planner_hint() for method in self.methods[: min(limit, 40)]]

    def command_for_call(self, *, method_name: str, arguments: dict[str, Any], reason: str) -> TripletexCommand:
        method = self.get(method_name)
        if method is None:
            raise GeneratedMethodError(f"Unknown generated API method: {method_name}")
        return method.build_command(arguments=arguments, reason=reason)


@lru_cache(maxsize=1)
def _load_generated_method_registry() -> GeneratedAPIMethodRegistry:
    spec_path = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    components = spec.get("components") or {}
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise GeneratedMethodError("OpenAPI spec is missing a valid 'paths' object.")

    methods: list[GeneratedMethodSpec] = []
    seen_method_names: set[str] = set()
    for template_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for http_method, operation in path_item.items():
            if http_method.lower() not in {"get", "post", "put", "delete"}:
                continue
            if not isinstance(operation, dict):
                continue

            operation_id = str(operation.get("operationId") or "").strip()
            method_name = _method_name_from_operation(http_method.upper(), str(template_path), operation_id)
            if method_name in seen_method_names:
                raise GeneratedMethodError(f"Duplicate generated API method name: {method_name}")
            seen_method_names.add(method_name)
            summary = str(operation.get("summary") or operation_id or "").strip()
            parameters = _resolve_parameters(operation.get("parameters") or [], components)
            path_arguments = tuple(
                _parameter_argument_spec(parameter, location="path", components=components)
                for parameter in parameters
                if parameter.get("in") == "path"
            )
            query_arguments = tuple(
                _parameter_argument_spec(parameter, location="query", components=components)
                for parameter in parameters
                if parameter.get("in") == "query"
            )
            body_arguments, request_body_style, request_body_required = _request_body_arguments(
                operation.get("requestBody"),
                components=components,
            )
            methods.append(
                GeneratedMethodSpec(
                    method_name=method_name,
                    operation_id=operation_id or method_name,
                    http_method=http_method.upper(),
                    template_path=str(template_path),
                    summary=summary,
                    tags=tuple(str(tag) for tag in (operation.get("tags") or [])),
                    target_resource=_target_resource_from_path(str(template_path)),
                    path_arguments=path_arguments,
                    query_arguments=query_arguments,
                    body_arguments=body_arguments,
                    request_body_style=request_body_style,
                    request_body_required=request_body_required,
                )
            )

    methods.sort(key=lambda method: (method.target_resource, method.method_name))
    return GeneratedAPIMethodRegistry(methods)


def _parameter_argument_spec(
    parameter: dict[str, Any],
    *,
    location: str,
    components: dict[str, Any],
) -> MethodArgumentSpec:
    schema = _resolve_schema(parameter.get("schema"), components)
    return MethodArgumentSpec(
        name=str(parameter.get("name") or "").strip(),
        location=location,
        required=bool(parameter.get("required")),
        schema_type=_schema_type(schema),
        description=str(parameter.get("description") or "").strip(),
    )


def _request_body_arguments(
    request_body: Any,
    *,
    components: dict[str, Any],
) -> tuple[tuple[MethodArgumentSpec, ...], str, bool]:
    if not isinstance(request_body, dict):
        return (), "none", False

    resolved_request_body = _resolve_request_body(request_body, components)
    request_body_required = bool(resolved_request_body.get("required"))
    content = resolved_request_body.get("content") or {}
    if not isinstance(content, dict) or not content:
        if request_body_required:
            return (MethodArgumentSpec(name="body", location="body", required=True),), "raw", True
        return (), "none", False

    schema = _pick_request_body_schema(content)
    resolved_schema = _resolve_schema(schema, components)
    properties, required_fields = _extract_object_properties(resolved_schema, components)
    if properties:
        arguments: list[MethodArgumentSpec] = []
        for name, property_schema in sorted(properties.items()):
            arguments.append(
                MethodArgumentSpec(
                    name=name,
                    location="body",
                    required=request_body_required and name in required_fields,
                    schema_type=_schema_type(_resolve_schema(property_schema, components)),
                    description=str((property_schema or {}).get("description") or "").strip(),
                )
            )
        return tuple(arguments), "object", request_body_required

    return (
        (MethodArgumentSpec(name="body", location="body", required=request_body_required),),
        "raw",
        request_body_required,
    )


def _resolve_parameters(parameters: list[Any], components: dict[str, Any]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for parameter in parameters:
        if isinstance(parameter, dict) and "$ref" in parameter:
            resolved_parameter = _resolve_ref(parameter["$ref"], components)
            if isinstance(resolved_parameter, dict):
                resolved.append(resolved_parameter)
            continue
        if isinstance(parameter, dict):
            resolved.append(parameter)
    return resolved


def _resolve_request_body(request_body: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    if "$ref" not in request_body:
        return request_body
    resolved = _resolve_ref(request_body["$ref"], components)
    return resolved if isinstance(resolved, dict) else request_body


def _pick_request_body_schema(content: dict[str, Any]) -> Any:
    preferred = content.get("application/json")
    if isinstance(preferred, dict) and "schema" in preferred:
        return preferred.get("schema")
    for media_type in content.values():
        if isinstance(media_type, dict) and "schema" in media_type:
            return media_type.get("schema")
    return None


def _extract_object_properties(schema: Any, components: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    resolved = _resolve_schema(schema, components)
    if not isinstance(resolved, dict):
        return {}, set()

    properties: dict[str, Any] = {}
    required_fields: set[str] = set()

    for subschema in resolved.get("allOf") or []:
        sub_properties, sub_required = _extract_object_properties(subschema, components)
        properties.update(sub_properties)
        required_fields.update(sub_required)

    if isinstance(resolved.get("properties"), dict):
        properties.update(resolved["properties"])
    if isinstance(resolved.get("required"), list):
        required_fields.update(str(name) for name in resolved["required"])

    return properties, required_fields


def _resolve_schema(schema: Any, components: dict[str, Any], *, _seen: set[str] | None = None) -> Any:
    if not isinstance(schema, dict):
        return schema
    if "$ref" not in schema:
        return schema

    ref = str(schema["$ref"])
    seen = set(_seen or set())
    if ref in seen:
        return {}
    seen.add(ref)
    resolved = _resolve_ref(ref, components)
    if isinstance(resolved, dict) and "$ref" in resolved:
        return _resolve_schema(resolved, components, _seen=seen)
    return resolved


def _resolve_ref(ref: str, components: dict[str, Any]) -> Any:
    if not ref.startswith("#/"):
        return {}
    target: Any = {"components": components}
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(target, dict):
            return {}
        target = target.get(part)
    return target


def _method_name_from_operation(http_method: str, template_path: str, operation_id: str) -> str:
    if operation_id:
        tokens = [token for token in re.split(r"[^A-Za-z0-9]+", operation_id) if token]
        if tokens:
            return "".join(token[:1].upper() + token[1:] for token in tokens)

    fallback_tokens = [http_method.title()]
    for segment in template_path.strip("/").split("/"):
        if not segment:
            continue
        cleaned = segment.strip("{}")
        cleaned = cleaned.lstrip(":>")
        if not cleaned:
            continue
        fallback_tokens.extend(token[:1].upper() + token[1:] for token in re.split(r"[^A-Za-z0-9]+", cleaned) if token)
    return "".join(fallback_tokens)


def _target_resource_from_path(template_path: str) -> str:
    parts = [part for part in template_path.strip("/").split("/") if part]
    for part in parts:
        if part.startswith("{"):
            continue
        cleaned = part.lstrip(":>")
        if cleaned:
            return cleaned
    return "other"


def _schema_type(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type
    if "properties" in schema or "allOf" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return None


def _is_blank(value: Any) -> bool:
    return value is None or value == ""
