from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .tasking import TripletexCommand


class OpenAPIRegistryError(RuntimeError):
    pass


class OpenAPIValidationError(OpenAPIRegistryError):
    pass


@dataclass(frozen=True)
class OperationSpec:
    method: str
    template_path: str
    summary: str
    tags: tuple[str, ...]
    query_parameters: frozenset[str]
    required_query_parameters: frozenset[str]
    path_parameters: frozenset[str]
    request_body_required: bool
    allows_request_body: bool
    _path_pattern: re.Pattern[str]

    def matches(self, *, method: str, path: str) -> bool:
        return self.method == method and bool(self._path_pattern.fullmatch(path))

    def planner_hint(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.template_path,
            "summary": self.summary,
            "required_query_parameters": sorted(self.required_query_parameters),
            "allows_request_body": self.allows_request_body,
            "request_body_required": self.request_body_required,
        }


class TripletexOpenAPIRegistry:
    def __init__(self, operations: list[OperationSpec]):
        self.operations = operations

    @classmethod
    def from_default_spec(cls) -> "TripletexOpenAPIRegistry":
        return _load_default_registry()

    def validate_command(self, command: TripletexCommand) -> OperationSpec:
        operation = self.match_operation(method=command.method, path=command.path)
        if operation is None:
            raise OpenAPIValidationError(f"Command does not match any OpenAPI operation: {command.method} {command.path}")

        query_params = command.params or {}
        unknown_params = sorted(set(query_params) - set(operation.query_parameters))
        if unknown_params:
            raise OpenAPIValidationError(
                f"Unsupported query parameters for {command.method} {operation.template_path}: {', '.join(unknown_params)}"
            )

        missing_required = sorted(
            name for name in operation.required_query_parameters if query_params.get(name) in {None, ""}
        )
        if missing_required:
            raise OpenAPIValidationError(
                f"Missing required query parameters for {command.method} {operation.template_path}: {', '.join(missing_required)}"
            )

        if operation.request_body_required and command.json_body is None:
            raise OpenAPIValidationError(f"Request body is required for {command.method} {operation.template_path}")
        if not operation.allows_request_body and command.json_body is not None:
            raise OpenAPIValidationError(f"Request body is not allowed for {command.method} {operation.template_path}")

        return operation

    def match_operation(self, *, method: str, path: str) -> OperationSpec | None:
        normalized_method = method.upper()
        normalized_path = _normalize_path(path)
        for operation in self.operations:
            if operation.matches(method=normalized_method, path=normalized_path):
                return operation
        return None

    def planner_hints(self, *, target_resource: str | None = None, limit: int = 36) -> list[dict[str, Any]]:
        prefixes = _resource_prefixes(target_resource)
        selected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for operation in self.operations:
            if prefixes and not any(operation.template_path.startswith(prefix) for prefix in prefixes):
                continue
            key = (operation.method, operation.template_path)
            if key in seen:
                continue
            seen.add(key)
            selected.append(operation.planner_hint())
            if len(selected) >= limit:
                break

        if selected:
            return selected

        fallback: list[dict[str, Any]] = []
        for operation in self.operations:
            key = (operation.method, operation.template_path)
            if key in seen:
                continue
            seen.add(key)
            fallback.append(operation.planner_hint())
            if len(fallback) >= min(limit, 24):
                break
        return fallback


@lru_cache(maxsize=1)
def _load_default_registry() -> TripletexOpenAPIRegistry:
    spec_path = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OpenAPIRegistryError(f"OpenAPI spec file is missing: {spec_path}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAPIRegistryError(f"OpenAPI spec file is invalid JSON: {spec_path}") from exc

    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise OpenAPIRegistryError("OpenAPI spec is missing a valid 'paths' object.")

    operations: list[OperationSpec] = []
    for template_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "delete"}:
                continue
            if not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters") or []
            path_parameters = {
                parameter["name"]
                for parameter in parameters
                if isinstance(parameter, dict) and parameter.get("in") == "path" and "name" in parameter
            }
            query_parameters = {
                parameter["name"]
                for parameter in parameters
                if isinstance(parameter, dict) and parameter.get("in") == "query" and "name" in parameter
            }
            required_query_parameters = {
                parameter["name"]
                for parameter in parameters
                if isinstance(parameter, dict)
                and parameter.get("in") == "query"
                and parameter.get("required") is True
                and "name" in parameter
            }
            request_body = operation.get("requestBody")
            allows_request_body = isinstance(request_body, dict)
            request_body_required = bool(allows_request_body and request_body.get("required"))
            operations.append(
                OperationSpec(
                    method=method.upper(),
                    template_path=str(template_path),
                    summary=str(operation.get("summary") or operation.get("operationId") or "").strip(),
                    tags=tuple(str(tag) for tag in (operation.get("tags") or [])),
                    query_parameters=frozenset(query_parameters),
                    required_query_parameters=frozenset(required_query_parameters),
                    path_parameters=frozenset(path_parameters),
                    request_body_required=request_body_required,
                    allows_request_body=allows_request_body,
                    _path_pattern=_compile_path_pattern(str(template_path)),
                )
            )

    if not operations:
        raise OpenAPIRegistryError("No supported operations were loaded from OpenAPI spec.")

    operations.sort(
        key=lambda item: (
            _placeholder_count(item.template_path),
            -item.template_path.count("/"),
            item.template_path,
            item.method,
        )
    )
    return TripletexOpenAPIRegistry(operations)


def _compile_path_pattern(template_path: str) -> re.Pattern[str]:
    normalized = _normalize_path(template_path)
    parts = re.split(r"(\{[^/]+\})", normalized)
    pattern = "".join(r"[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part) for part in parts)
    return re.compile(f"^{pattern}$")


def _normalize_path(path: str) -> str:
    stripped = path.strip() or "/"
    if not stripped.startswith("/"):
        stripped = f"/{stripped}"
    return stripped.rstrip("/") or "/"


def _resource_prefixes(target_resource: str | None) -> tuple[str, ...]:
    mapping = {
        "employee": ("/employee",),
        "customer": ("/customer", "/deliveryAddress"),
        "product": ("/product",),
        "invoice": ("/invoice", "/order"),
        "order": ("/order", "/invoice"),
        "travelexpense": ("/travelExpense",),
        "project": ("/project",),
        "department": ("/department",),
        "ledger": (
            "/ledger/account",
            "/ledger/posting",
            "/ledger/voucher",
            "/ledger/vatType",
            "/ledger/vatSettings",
        ),
        "other": (
            "/employee",
            "/customer",
            "/product",
            "/invoice",
            "/order",
            "/travelExpense",
            "/project",
            "/department",
            "/ledger/account",
            "/ledger/posting",
            "/ledger/voucher",
            "/ledger/vatType",
            "/ledger/vatSettings",
        ),
    }
    key = (target_resource or "other").replace("_", "").replace("-", "").lower()
    return mapping.get(key, mapping["other"])


def _placeholder_count(template_path: str) -> int:
    return len(re.findall(r"\{[^/]+\}", template_path))
