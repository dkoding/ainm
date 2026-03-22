from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlparse

from app.llm.contract_utils import input_names, split_required_inputs


_DOC_PREFIXES = {
    "flow": "flow",
    "command": "command",
    "raw_operation": "raw",
}
_DOC_TYPES_BY_PREFIX = {value: key for key, value in _DOC_PREFIXES.items()}


def retrieval_document_filename(doc_type: str, canonical_name: str, *, extension: str = "md") -> str:
    prefix = _DOC_PREFIXES[doc_type]
    encoded_name = quote(canonical_name, safe="._-")
    clean_extension = extension.lstrip(".") or "md"
    return f"{prefix}__{encoded_name}.{clean_extension}"


def parse_retrieval_document_ref(reference: str) -> tuple[str, str] | None:
    candidate = reference.strip()
    if not candidate:
        return None
    parsed = urlparse(candidate)
    basename = PurePosixPath(parsed.path or candidate).name
    if "__" not in basename or "." not in basename:
        return None
    prefix, remainder = basename.split("__", 1)
    if "." not in remainder:
        return None
    encoded_name, _extension = remainder.rsplit(".", 1)
    doc_type = _DOC_TYPES_BY_PREFIX.get(prefix)
    if not doc_type or not encoded_name:
        return None
    return doc_type, unquote(encoded_name)


def parse_retrieval_document_text(text: str) -> tuple[str, str] | None:
    candidate = text.strip()
    if not candidate:
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        doc_type = str(payload.get("docType") or payload.get("doc_type") or "").strip()
        if doc_type == "raw":
            doc_type = "raw_operation"
        if doc_type == "flow":
            name = str(payload.get("flowName") or payload.get("flow_name") or "").strip()
            return (doc_type, name) if name else None
        if doc_type == "command":
            name = str(payload.get("commandName") or payload.get("command_name") or "").strip()
            return (doc_type, name) if name else None
        if doc_type == "raw_operation":
            name = str(payload.get("operationId") or payload.get("operation_id") or "").strip()
            return (doc_type, name) if name else None

    fields: dict[str, str] = {}
    for line in candidate.splitlines()[:32]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip()
    doc_type = fields.get("doc_type", "")
    if doc_type == "raw":
        doc_type = "raw_operation"
    if doc_type == "flow" and fields.get("flow_name"):
        return doc_type, fields["flow_name"]
    if doc_type == "command" and fields.get("command_name"):
        return doc_type, fields["command_name"]
    if doc_type == "raw_operation" and fields.get("operation_id"):
        return doc_type, fields["operation_id"]
    return None


def render_flow_retrieval_doc(flow: dict[str, Any]) -> str:
    legal_inputs = input_names(flow.get("inputs", {}))
    required_inputs, optional_inputs = split_required_inputs(legal_inputs, flow.get("inputSpec"))
    notes = flow.get("notes") or []
    input_semantics = flow.get("inputSemantics") or {}
    return "\n".join(
        [
            "doc_type: flow",
            f"flow_name: {flow['flowName']}",
            f"use_when: {flow.get('useWhen', '')}",
            f"result: {flow.get('result', '')}",
            f"command_names: {', '.join(flow.get('commandNames', []))}",
            f"required_inputs: {', '.join(required_inputs) if required_inputs else '-'}",
            f"optional_inputs: {', '.join(optional_inputs) if optional_inputs else '-'}",
            f"input_semantics: {json.dumps(input_semantics, ensure_ascii=False, sort_keys=True)}",
            f"notes: {' | '.join(notes) if notes else '-'}",
        ]
    )


def render_command_retrieval_doc(command: dict[str, Any], raw_meta: dict[str, Any]) -> str:
    legal_inputs = list(input_names(command.get("inputs", {})))
    body_fields = _command_body_fields(command, raw_meta)
    if command.get("allowsBodyPassthrough"):
        legal_inputs.extend(["body", "payload"])
        legal_inputs.extend(body_fields)
    legal_inputs = sorted(dict.fromkeys(name for name in legal_inputs if name))
    required_inputs, optional_inputs = split_required_inputs(legal_inputs, command.get("inputSpec"))
    workflow_membership = command.get("workflowMembership") or []
    notes = command.get("notes") or []
    return "\n".join(
        [
            "doc_type: command",
            f"command_name: {command['commandName']}",
            f"operation_id: {command['operationId']}",
            f"purpose: {command.get('purpose', '')}",
            f"technical_flow_family: {command.get('technicalFlowFamily', '')}",
            f"selector_family: {command.get('selectorFamily', '')}",
            f"required_inputs: {', '.join(required_inputs) if required_inputs else '-'}",
            f"optional_inputs: {', '.join(optional_inputs) if optional_inputs else '-'}",
            f"body_fields: {', '.join(body_fields) if body_fields else '-'}",
            f"workflow_membership: {', '.join(workflow_membership) if workflow_membership else '-'}",
            f"input_semantics: {json.dumps(command.get('inputSemantics') or {}, ensure_ascii=False, sort_keys=True)}",
            f"notes: {' | '.join(notes) if notes else '-'}",
        ]
    )


def render_raw_operation_retrieval_doc(operation: dict[str, Any]) -> str:
    body_schema = next(iter(operation.get("requestBody", {}).get("content", {}).values()), {})
    body_fields = sorted(
        name
        for name, value in body_schema.get("properties", {}).items()
        if not value.get("readOnly")
    )
    required_query = sorted(param["name"] for param in operation.get("queryParams", []) if param.get("required"))
    optional_query = sorted(param["name"] for param in operation.get("queryParams", []) if not param.get("required"))
    path_params = sorted(param["name"] for param in operation.get("pathParams", []))
    semantic_aliases = sorted(operation.get("semanticAliases") or [])
    anti_triggers = sorted(operation.get("antiTriggers") or [])
    return "\n".join(
        [
            "doc_type: raw_operation",
            f"operation_id: {operation['operationId']}",
            f"http_method: {operation.get('method', '')}",
            f"http_path: {operation.get('path', '')}",
            f"purpose: {operation.get('purpose', '')}",
            f"domain: {operation.get('domain', '')}",
            f"subdomain: {operation.get('subdomain', '')}",
            f"technical_flow_families: {', '.join(operation.get('technicalFlowFamilies', []))}",
            f"semantic_aliases: {', '.join(semantic_aliases) if semantic_aliases else '-'}",
            f"required_path_params: {', '.join(path_params) if path_params else '-'}",
            f"required_query_params: {', '.join(required_query) if required_query else '-'}",
            f"optional_query_params: {', '.join(optional_query) if optional_query else '-'}",
            f"request_body_kind: {operation.get('requestBody', {}).get('kind', 'none')}",
            f"writable_body_fields: {', '.join(body_fields) if body_fields else '-'}",
            f"anti_triggers: {', '.join(anti_triggers) if anti_triggers else '-'}",
        ]
    )


def _command_body_fields(command: dict[str, Any], raw_meta: dict[str, Any]) -> list[str]:
    if not command.get("allowsBodyPassthrough"):
        return []
    body_schema = next(iter(raw_meta.get("requestBody", {}).get("content", {}).values()), {})
    return sorted(
        name
        for name, value in body_schema.get("properties", {}).items()
        if not value.get("readOnly")
    )
