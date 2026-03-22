from __future__ import annotations

import base64
import re
from typing import Any

from app.contracts.execution import ExecutionContext
from app.raw.catalog import RawCatalog, load_raw_catalog
from app.raw.errors import RawExecutionError
from app.raw.transport import TripletexTransport


class RawExecutor:
    def __init__(self, catalog: RawCatalog | None = None, transport: TripletexTransport | None = None) -> None:
        self.catalog = catalog or load_raw_catalog()
        self.transport = transport or TripletexTransport()

    def execute(self, operation_id: str, arguments: dict[str, Any], context: ExecutionContext) -> Any:
        operation = self.catalog.get(operation_id)
        params = dict(arguments)
        path = self._interpolate_path(operation["path"], operation["pathParams"], params)
        query = self._collect_query(operation["queryParams"], params)
        json_body, multipart_data, multipart_files = self._build_body(operation["requestBody"], params)
        self._validate_remaining_required(operation, query, json_body, multipart_data, multipart_files, params)
        return self.transport.request(
            context=context,
            method=operation["method"],
            path=path,
            params=query,
            json_body=json_body,
            multipart_data=multipart_data,
            multipart_files=multipart_files,
        )

    def _interpolate_path(
        self,
        path_template: str,
        path_params: list[dict[str, Any]],
        arguments: dict[str, Any],
    ) -> str:
        path = path_template
        for parameter in path_params:
            name = parameter["name"]
            if name not in arguments or arguments[name] is None:
                raise RawExecutionError(message=f"Missing required path parameter: {name}")
            path = path.replace(f"{{{name}}}", str(arguments.pop(name)))
        return path

    def _collect_query(self, query_params: list[dict[str, Any]], arguments: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {}
        for parameter in query_params:
            name = parameter["name"]
            if name in arguments and arguments[name] is not None:
                query[name] = arguments.pop(name)
        return query

    def _build_body(
        self,
        body_meta: dict[str, Any],
        arguments: dict[str, Any],
    ) -> tuple[Any, dict[str, Any] | None, dict[str, Any] | None]:
        if not body_meta:
            return None, None, None
        explicit_body = arguments.pop("body", None)
        if body_meta["kind"] == "multipart":
            source = explicit_body or {}
            if not isinstance(source, dict):
                raise RawExecutionError(message="Multipart operations require a dict body.")
            data: dict[str, Any] = {}
            files: dict[str, Any] = {}
            for key, value in source.items():
                if isinstance(value, dict) and "content_base64" in value:
                    payload = base64.b64decode(value["content_base64"])
                    files[key] = (value.get("filename", key), payload, value.get("mime_type", "application/octet-stream"))
                else:
                    data[key] = value
            return None, data, files
        if explicit_body is not None:
            if not isinstance(explicit_body, (dict, list)):
                raise RawExecutionError(message="JSON request bodies must be dict or list values.")
            return explicit_body, None, None
        content = body_meta.get("content", {})
        json_schema = next(iter(content.values()), {})
        if json_schema.get("type") == "array":
            return None, None, None
        allowed_properties = {
            key for key, value in json_schema.get("properties", {}).items() if not value.get("readOnly")
        }
        body: dict[str, Any] = {}
        for key in list(arguments.keys()):
            if key in allowed_properties:
                body[key] = arguments.pop(key)
        return body or None, None, None

    def _validate_remaining_required(
        self,
        operation: dict[str, Any],
        query: dict[str, Any],
        json_body: dict[str, Any] | None,
        multipart_data: dict[str, Any] | None,
        multipart_files: dict[str, Any] | None,
        arguments: dict[str, Any],
    ) -> None:
        missing_query = [
            parameter["name"]
            for parameter in operation["queryParams"]
            if parameter["required"] and parameter["name"] not in query
        ]
        if missing_query:
            raise RawExecutionError(message=f"Missing required query parameters: {', '.join(missing_query)}")
        request_body = operation["requestBody"]
        if request_body.get("required") and json_body is None and multipart_data is None:
            raise RawExecutionError(message="Missing required request body.")
        if request_body and isinstance(json_body, dict):
            schema = next(iter(request_body.get("content", {}).values()), {})
            required_properties = schema.get("required", [])
            missing_properties = [name for name in required_properties if name not in json_body]
            if missing_properties:
                raise RawExecutionError(
                    message=f"Missing required body properties: {', '.join(missing_properties)}"
                )
        if request_body and request_body.get("kind") == "multipart":
            schema = next(iter(request_body.get("content", {}).values()), {})
            required_properties = schema.get("required", [])
            multipart_keys = set((multipart_data or {}).keys()) | set((multipart_files or {}).keys())
            missing_properties = [name for name in required_properties if name not in multipart_keys]
            if missing_properties:
                raise RawExecutionError(
                    message=f"Missing required multipart properties: {', '.join(missing_properties)}"
                )
        unused = {key: value for key, value in arguments.items() if value is not None}
        if unused:
            names = ", ".join(sorted(unused))
            raise RawExecutionError(message=f"Unrecognized parameters for {operation['operationId']}: {names}")
