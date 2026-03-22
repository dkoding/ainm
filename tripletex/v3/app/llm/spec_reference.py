from __future__ import annotations

import hashlib
import json
from typing import Any

from app.raw import load_raw_catalog
from app.utils import PROJECT_ROOT
from app.wrapper import load_wrapper_catalog


OPENAPI_PATH = PROJECT_ROOT / "docs" / "openapi.json"


class SpecReferenceBuilder:
    def __init__(self) -> None:
        self.raw_catalog = load_raw_catalog()
        self.wrapper_catalog = load_wrapper_catalog()

    def build(self, *, context_slice: dict[str, Any]) -> list[dict[str, Any]]:
        operation_ids = self._candidate_operation_ids(context_slice)
        if not operation_ids:
            return []
        bundle = {
            "source": {
                "path": "docs/openapi.json",
                "sha256": self._openapi_sha256(),
            },
            "candidateOperationIds": operation_ids,
            "operations": [self._operation_bundle(operation_id) for operation_id in operation_ids],
        }
        return [
            {
                "name": "candidate_openapi_bundle.json",
                "mimeType": "application/json",
                "instruction": (
                    "This is an exact raw OpenAPI slice extracted from the authoritative docs/openapi.json for the current candidate operations. "
                    "Use it only for raw_operation steps and explicit raw body/payload passthrough. "
                    "For business flows and friendly commands, the wrapper contract in context.apiContract plus selectorFamilies/payloadFamilies stays authoritative."
                ),
                "content": json.dumps(bundle, ensure_ascii=False, separators=(",", ":")),
            }
        ]

    def _candidate_operation_ids(self, context_slice: dict[str, Any]) -> list[str]:
        operation_ids: list[str] = []
        seen: set[str] = set()
        raw_contract = context_slice.get("rawApiContract", {})
        for operation_id in raw_contract.get("candidateOperationIds", []) or []:
            if isinstance(operation_id, str) and operation_id and operation_id not in seen and self.raw_catalog.has(operation_id):
                seen.add(operation_id)
                operation_ids.append(operation_id)
        api_contract = context_slice.get("apiContract", {})
        for command in api_contract.get("candidateCommands", []) or []:
            if not isinstance(command, dict):
                continue
            operation_id = str(command.get("operationId", "")).strip()
            if operation_id and operation_id not in seen and self.raw_catalog.has(operation_id):
                seen.add(operation_id)
                operation_ids.append(operation_id)
        return operation_ids

    def _operation_bundle(self, operation_id: str) -> dict[str, Any]:
        operation = self.raw_catalog.get(operation_id)
        request_body = dict(operation.get("requestBody", {}))
        content = request_body.get("content", {})
        content_type = next(iter(content.keys()), "")
        body_schema = next(iter(content.values()), {}) if content else {}
        return {
            "operationId": operation_id,
            "method": operation.get("method"),
            "path": operation.get("path"),
            "purpose": operation.get("purpose"),
            "technicalFlowFamilies": operation.get("technicalFlowFamilies", []),
            "parameters": [
                self._parameter_bundle(parameter)
                for parameter in [*operation.get("pathParams", []), *operation.get("queryParams", [])]
            ],
            "requestBody": {
                "kind": request_body.get("kind"),
                "required": bool(request_body.get("required")),
                "contentType": content_type,
                "schema": self._prune_schema(body_schema),
            },
            "wrapperCommands": sorted(self._wrapper_commands_for_operation(operation_id)),
        }

    def _parameter_bundle(self, parameter: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": parameter.get("name"),
            "in": parameter.get("in"),
            "required": bool(parameter.get("required")),
            "description": parameter.get("description", ""),
            "schema": self._prune_schema(parameter),
        }

    def _wrapper_commands_for_operation(self, operation_id: str) -> set[str]:
        return {
            name
            for name, command in self.wrapper_catalog.commands.items()
            if command.get("operationId") == operation_id
        }

    def _prune_schema(self, schema: Any) -> Any:
        if not isinstance(schema, dict):
            return schema
        pruned: dict[str, Any] = {}
        for key in (
            "type",
            "format",
            "enum",
            "description",
            "default",
            "nullable",
            "pattern",
            "minimum",
            "maximum",
            "minLength",
            "maxLength",
            "itemsRef",
            "ref",
        ):
            if schema.get(key) is not None:
                pruned[key] = schema[key]
        properties = schema.get("properties")
        if isinstance(properties, dict):
            pruned_properties: dict[str, Any] = {}
            for name, value in properties.items():
                if isinstance(value, dict) and value.get("readOnly"):
                    continue
                pruned_properties[name] = self._prune_schema(value)
            if pruned_properties:
                pruned["properties"] = pruned_properties
                pruned.setdefault("type", "object")
        items = schema.get("items")
        if items is not None:
            pruned["items"] = self._prune_schema(items)
            pruned.setdefault("type", "array")
        required = schema.get("required")
        if isinstance(required, list) and required:
            if "properties" in pruned:
                pruned["required"] = [name for name in required if name in pruned["properties"]]
            else:
                pruned["required"] = list(required)
        for key in ("anyOf", "oneOf", "allOf"):
            variants = schema.get(key)
            if isinstance(variants, list) and variants:
                pruned[key] = [self._prune_schema(item) for item in variants]
        additional = schema.get("additionalProperties")
        if isinstance(additional, bool):
            pruned["additionalProperties"] = additional
        elif isinstance(additional, dict):
            pruned["additionalProperties"] = self._prune_schema(additional)
        return pruned

    def _openapi_sha256(self) -> str:
        return _openapi_sha256()


def _openapi_sha256() -> str:
    digest = hashlib.sha256()
    digest.update(OPENAPI_PATH.read_bytes())
    return digest.hexdigest()
