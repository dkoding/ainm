from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.semantic_contract import (
    clean_contract_name,
    command_input_semantics,
    copy_payload_families,
    copy_selector_families,
    flow_input_semantics,
    selector_family_for_command,
)


OPENAPI_PATH = ROOT / "docs" / "openapi.json"
DESC_PATH = ROOT / "DESC.md"
GENERATED_DIR = ROOT / "app" / "generated"

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
CONTROL_FIELDS = {"date_window"}
SPECIAL_INPUT_TARGETS = {
    "invoiceable_lines": "orderLines",
    "line_items": "orderLines",
    "order_lines": "orderLines",
    "travel_details": "travelDetails",
}
MANUAL_BINDINGS = {
    ("customer.search", "name"): {"targetSection": "query", "targetName": "customerName", "valueStrategy": "plain"},
    ("invoice.create", "invoice_comment"): {"targetSection": "body", "targetName": "comment", "valueStrategy": "plain"},
    ("incoming_invoice.add_payment", "payment_type_client_uuid"): {
        "targetSection": "body",
        "targetName": "paymentTypeClientUUId",
        "valueStrategy": "plain",
    },
    ("travel_expense.cost.create", "travel_expense_ref"): {
        "targetSection": "body",
        "targetName": "travelExpense",
        "valueStrategy": "ref_object",
    },
    ("travel_expense.mileage.create", "travel_expense_ref"): {
        "targetSection": "body",
        "targetName": "travelExpense",
        "valueStrategy": "ref_object",
    },
    ("travel_expense.per_diem.create", "travel_expense_ref"): {
        "targetSection": "body",
        "targetName": "travelExpense",
        "valueStrategy": "ref_object",
    },
    ("travel_expense.accommodation.create", "travel_expense_ref"): {
        "targetSection": "body",
        "targetName": "travelExpense",
        "valueStrategy": "ref_object",
    },
    ("ledger.account.create", "currency_ref"): {"targetSection": "body", "targetName": "currency", "valueStrategy": "ref_object"},
    ("order.create", "currency_ref"): {"targetSection": "body", "targetName": "currency", "valueStrategy": "ref_object"},
    ("product.create", "currency_ref"): {"targetSection": "body", "targetName": "currency", "valueStrategy": "ref_object"},
    ("project.create", "currency_ref"): {"targetSection": "body", "targetName": "currency", "valueStrategy": "ref_object"},
    ("travel_rate_category.search", "requires_overnight_accommodation"): {
        "targetSection": "query",
        "targetName": "isRequiresOvernightAccommodation",
        "valueStrategy": "plain",
    },
    ("ledger.voucher.import_document", "attachment_id"): {
        "targetSection": "body",
        "targetName": "file",
        "valueStrategy": "attachment_file",
    },
    ("supplier_invoice.voucher.update_postings", "postings"): {
        "targetSection": "body",
        "targetName": "body",
        "valueStrategy": "body_merge",
    },
}


def snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = value.replace("-", "_").replace("/", "_").replace(".", "_")
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value.lower()


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def camel_case(value: str) -> str:
    parts = snake_case(value).split("_")
    if not parts:
        return value
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def tokenise(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(token) > 2]


def extract_backticked_values(text: str) -> list[str]:
    values = [match.strip() for match in re.findall(r"`([^`]+)`", text)]
    if values:
        return values
    return [part.strip() for part in text.split(",") if part.strip()]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dereference_schema(spec: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
    if not schema:
        return {}
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return {"$ref": ref}
        current: Any = spec
        for part in ref[2:].split("/"):
            current = current[part]
        return dereference_schema(spec, current)
    if "allOf" in schema:
        merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for item in schema["allOf"]:
            resolved = dereference_schema(spec, item)
            merged["properties"].update(resolved.get("properties", {}))
            merged["required"].extend(resolved.get("required", []))
        merged["required"] = sorted(set(merged["required"]))
        return merged
    return schema


def schema_summary(
    spec: dict[str, Any],
    schema: dict[str, Any] | None,
    *,
    depth: int = 0,
    max_depth: int = 1,
    seen_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not schema:
        return {}
    ref = schema.get("$ref")
    if ref and (ref in seen_refs or depth >= max_depth):
        resolved = dereference_schema(spec, schema)
        schema_type = resolved.get("type")
        if schema_type is None:
            if resolved.get("properties"):
                schema_type = "object"
            elif resolved.get("items"):
                schema_type = "array"
        return {
            "type": schema_type,
            "required": resolved.get("required", []),
            "properties": {},
            "itemsRef": resolved.get("items", {}).get("$ref"),
            "enum": resolved.get("enum"),
            "format": resolved.get("format"),
            "readOnly": bool(resolved.get("readOnly")),
            "ref": ref,
        }
    resolved = dereference_schema(spec, schema)
    if not resolved:
        return {}
    child_seen_refs = seen_refs + ((ref,) if ref else ())
    summary = {
        "type": resolved.get("type"),
        "required": resolved.get("required", []),
        "properties": {},
        "itemsRef": resolved.get("items", {}).get("$ref"),
        "enum": resolved.get("enum"),
        "format": resolved.get("format"),
        "readOnly": bool(resolved.get("readOnly")),
        "ref": ref,
    }
    if depth >= max_depth:
        return summary
    properties = {}
    for name, value in resolved.get("properties", {}).items():
        properties[name] = schema_summary(
            spec,
            value,
            depth=depth + 1,
            max_depth=max_depth,
            seen_refs=child_seen_refs,
        )
    summary["properties"] = properties
    items = resolved.get("items")
    if items:
        summary["items"] = schema_summary(
            spec,
            items,
            depth=depth + 1,
            max_depth=max_depth,
            seen_refs=child_seen_refs,
        )
    return summary


def merged_parameters(path_item: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    by_name: dict[tuple[str, str], dict[str, Any]] = {}
    for container in (path_item.get("parameters", []), operation.get("parameters", [])):
        for parameter in container:
            if "$ref" in parameter:
                raise ValueError(f"Unexpected unresolved parameter ref: {parameter['$ref']}")
            key = (parameter["in"], parameter["name"])
            by_name[key] = parameter
    return list(by_name.values())


def parameter_summary(parameter: dict[str, Any]) -> dict[str, Any]:
    schema = parameter.get("schema", {})
    return {
        "name": parameter["name"],
        "in": parameter["in"],
        "required": bool(parameter.get("required")),
        "description": parameter.get("description", ""),
        "type": schema.get("type"),
        "format": schema.get("format"),
        "default": schema.get("default"),
        "enum": schema.get("enum"),
        "style": parameter.get("style"),
        "explode": parameter.get("explode"),
    }


def request_body_summary(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    request_body = operation.get("requestBody")
    if not request_body:
        return {}
    content = request_body.get("content", {})
    summaries: dict[str, Any] = {}
    for content_type, value in content.items():
        summaries[content_type] = schema_summary(spec, value.get("schema"))
    if any(content_type.startswith("multipart/") for content_type in content):
        kind = "multipart"
    elif content:
        kind = "json"
    else:
        kind = "unknown"
    return {
        "required": bool(request_body.get("required")),
        "kind": kind,
        "contentTypes": sorted(content.keys()),
        "content": summaries,
    }


def response_summary(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    responses = operation.get("responses", {})
    status_code = None
    for candidate in sorted(responses.keys()):
        if candidate.startswith("2"):
            status_code = candidate
            break
    if status_code is None:
        return {}
    response = responses[status_code]
    content = response.get("content", {})
    return {
        "statusCode": status_code,
        "description": response.get("description", ""),
        "contentTypes": sorted(content.keys()),
    }


def split_path(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def derive_domain_subdomain(path: str) -> tuple[str, str]:
    domain = "root"
    subdomain = "root"
    segments = split_path(path)
    cleaned: list[str] = []
    for segment in segments:
        if segment.startswith("{"):
            continue
        if segment.startswith(":") or segment.startswith(">"):
            continue
        cleaned.append(snake_case(segment))
    if cleaned:
        domain = cleaned[0]
    if len(cleaned) > 1:
        subdomain = cleaned[1]
    return domain, subdomain


def extract_action_marker(path: str) -> str | None:
    for segment in split_path(path):
        if segment.startswith(":"):
            return snake_case(segment[1:])
        if segment.startswith(">"):
            return snake_case(segment[1:])
    return None


def derive_technical_families(path: str, method: str) -> list[str]:
    domain, subdomain = derive_domain_subdomain(path)
    prefix = domain if subdomain == "root" else f"{domain}.{subdomain}"
    action_marker = extract_action_marker(path)
    if action_marker:
        families = [f"{prefix}.{action_marker}"]
        if action_marker in {"approve", "reject", "deliver", "undeliver"}:
            families.append(f"{prefix}.approval")
        if action_marker in {"payment", "add_payment"}:
            families.append(f"{prefix}.payment")
        if action_marker in {"invoice", "create_credit_note", "create_credit_note"}:
            families.append(f"{prefix}.invoice")
        if action_marker in {"reverse", "correct", "close"}:
            families.append(f"{prefix}.reverse_or_correct")
        if action_marker in {"download", "pdf", "print"}:
            families.append(f"{prefix}.document")
        return sorted(set(families))
    if "/>" in path and method == "get":
        return [f"{prefix}.read", f"{prefix}.reporting"]
    if method == "get":
        family = "read" if re.search(r"/\{[^}]+\}$", path) else "resolve"
    elif method == "post":
        family = "create"
    elif method == "put":
        family = "update"
    elif method == "delete":
        family = "delete"
    else:
        family = "action"
    return [f"{prefix}.{family}"]


def derive_safety_class(method: str, path: str, action_marker: str | None) -> str:
    if method == "get":
        return "read_only"
    if method == "delete":
        return "destructive"
    if action_marker in {"reverse", "create_credit_note", "close"}:
        return "high_risk"
    if action_marker in {"payment", "add_payment", "approve", "deliver", "create_vouchers"}:
        return "state_change"
    return "mutation"


def derive_conformance_policy(path: str, operation_id: str) -> str | None:
    lowered = f"{path} {operation_id}".lower()
    if "entitlement" in lowered or "usertype" in lowered:
        return "employee_access_mapping"
    if "salesmodules" in lowered or "/department" in lowered:
        return "department_module_activation"
    if "createcreditnote" in lowered or "creditnote" in lowered:
        return "invoice_credit_note"
    if "travelexpense" in lowered:
        return "travel_expense_payload"
    if "supplierinvoice" in lowered and "payment" in lowered:
        return "supplier_invoice_payment"
    if "attachment" in lowered or "document" in lowered:
        return "attachment_accounting"
    return None


def derive_semantic_aliases(operation_id: str, path: str, summary: str, tags: list[str]) -> list[str]:
    values = set(tokenise(operation_id))
    values.update(tokenise(path))
    values.update(tokenise(summary))
    for tag in tags:
        values.update(tokenise(tag))
    return sorted(values)


def build_operation_catalog(spec: dict[str, Any]) -> dict[str, Any]:
    operations: dict[str, Any] = {}
    method_index: dict[tuple[str, str], str] = {}
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            operation_id = operation["operationId"]
            parameters = merged_parameters(path_item, operation)
            path_params = [parameter_summary(item) for item in parameters if item["in"] == "path"]
            query_params = [parameter_summary(item) for item in parameters if item["in"] == "query"]
            domain, subdomain = derive_domain_subdomain(path)
            action_marker = extract_action_marker(path)
            operation_summary = operation.get("summary", "")
            technical_families = derive_technical_families(path, method.lower())
            catalog_entry = {
                "operationId": operation_id,
                "method": method.upper(),
                "path": path,
                "domain": domain,
                "subdomain": subdomain,
                "purpose": operation_summary,
                "semanticAliases": derive_semantic_aliases(operation_id, path, operation_summary, operation.get("tags", [])),
                "antiTriggers": [],
                "pathParams": path_params,
                "queryParams": query_params,
                "parameterSemantics": {
                    item["name"]: item.get("description", "") for item in parameters if item.get("description")
                },
                "requestBody": request_body_summary(spec, operation),
                "responseSchema": response_summary(spec, operation),
                "safetyClass": derive_safety_class(method.lower(), path, action_marker),
                "technicalFlowFamily": technical_families[0],
                "technicalFlowFamilies": technical_families,
                "actionMarker": action_marker,
                "conformancePolicyKey": derive_conformance_policy(path, operation_id),
                "tags": operation.get("tags", []),
            }
            operations[operation_id] = catalog_entry
            method_index[(method.upper(), path)] = operation_id
    return {
        "specVersion": spec.get("info", {}).get("version"),
        "operationCount": len(operations),
        "operations": operations,
        "methodIndex": {f"{method} {path}": op_id for (method, path), op_id in sorted(method_index.items())},
    }


@dataclass
class ParsedCommand:
    name: str
    raw_method: str
    raw_path: str
    purpose: str
    workflows: list[str]
    inputs: list[str]
    inputSpec: str
    notes: list[str]


def binding_candidates(input_name: str) -> list[str]:
    base = clean_contract_name(input_name)
    candidates = [base, camel_case(base)]
    if base.endswith("_ref"):
        stem = base[:-4]
        camel = camel_case(stem)
        candidates.extend([stem, camel, f"{camel}Id", f"{camel}Ids"])
    else:
        camel = camel_case(base)
        candidates.extend([f"{camel}Id", f"{camel}Ids"])
    special = SPECIAL_INPUT_TARGETS.get(base)
    if special:
        candidates.insert(0, special)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


def binding_strategy(input_name: str, target_name: str, section: str, body_properties: dict[str, Any]) -> str:
    if clean_contract_name(input_name).endswith("_ref"):
        if section in {"path", "query"}:
            return "ref_id"
        body_property = body_properties.get(target_name, {})
        if body_property.get("type") == "array":
            return "ref_list"
        return "ref_object"
    if target_name in {"body", "payload"}:
        return "body_merge"
    return "plain"


def build_input_bindings(command_name: str, command: ParsedCommand, raw_meta: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    path_names = {item["name"] for item in raw_meta["pathParams"]}
    query_names = {item["name"] for item in raw_meta["queryParams"]}
    body_schema = next(iter(raw_meta["requestBody"].get("content", {}).values()), {})
    body_properties = {
        key: value
        for key, value in body_schema.get("properties", {}).items()
        if not value.get("readOnly")
    }
    bindings: dict[str, Any] = {}
    unmapped: list[str] = []
    for original in command.inputs:
        input_name = clean_contract_name(original)
        if input_name in CONTROL_FIELDS:
            bindings[input_name] = {
                "targetSection": "control",
                "targetName": input_name,
                "valueStrategy": "plain",
            }
            continue
        manual = MANUAL_BINDINGS.get((command_name, input_name))
        if manual is not None:
            bindings[input_name] = manual
            continue
        matched: tuple[str, str] | None = None
        for candidate in binding_candidates(input_name):
            if candidate in path_names:
                matched = ("path", candidate)
                break
            if candidate in query_names:
                matched = ("query", candidate)
                break
            if candidate in body_properties:
                matched = ("body", candidate)
                break
        if matched is None:
            unmapped.append(input_name)
            continue
        section, target = matched
        bindings[input_name] = {
            "targetSection": section,
            "targetName": target,
            "valueStrategy": binding_strategy(input_name, target, section, body_properties),
        }
        semantics = command_input_semantics(command_name, input_name)
        if semantics.get("kind") != "scalar":
            bindings[input_name]["semantic"] = semantics
    if raw_meta["requestBody"]:
        bindings["body"] = {"targetSection": "body", "targetName": "body", "valueStrategy": "body_merge"}
        bindings["payload"] = {"targetSection": "body", "targetName": "payload", "valueStrategy": "body_merge"}
    return bindings, unmapped


def parse_commands(desc_text: str) -> list[ParsedCommand]:
    start = desc_text.index("## 5. Command Catalog")
    end = desc_text.index("## 6. Flow Catalog")
    lines = desc_text[start:end].splitlines()
    commands: list[ParsedCommand] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^- `([^`]+)`$", line)
        if not match:
            index += 1
            continue
        name = match.group(1)
        raw_method = ""
        raw_path = ""
        purpose = ""
        workflows: list[str] = []
        inputs: list[str] = []
        input_spec = ""
        notes: list[str] = []
        index += 1
        while index < len(lines):
            current = lines[index]
            if current.startswith("- `") or current.startswith("### "):
                break
            current_match = re.match(r"^  - ([^:]+): ?(.*)$", current)
            if current_match:
                label = current_match.group(1).strip()
                value = current_match.group(2).strip()
                if label == "Raw Tripletex method":
                    method_path = extract_backticked_values(value)[0]
                    raw_method, raw_path = method_path.split(" ", 1)
                elif label == "Purpose":
                    purpose = value
                elif label == "Workflows":
                    workflows = [item for item in extract_backticked_values(value) if item]
                elif label == "Inputs":
                    input_spec = value
                    inputs = [clean_contract_name(item) for item in extract_backticked_values(value)]
                elif label == "Notes":
                    notes.append(value)
            index += 1
        commands.append(
            ParsedCommand(
                name=name,
                raw_method=raw_method,
                raw_path=raw_path,
                purpose=purpose,
                workflows=workflows,
                inputs=inputs,
                inputSpec=input_spec,
                notes=notes,
            )
        )
    return commands


def parse_flows(desc_text: str) -> dict[str, Any]:
    start = desc_text.index("## 6. Flow Catalog")
    end = desc_text.index("## 7. Full OpenAPI Coverage Model")
    lines = desc_text[start:end].splitlines()
    flows: dict[str, Any] = {}
    index = 0
    current_flow: dict[str, Any] | None = None
    current_section: str | None = None
    while index < len(lines):
        line = lines[index]
        heading = re.match(r"^### 6\.\d+ `([^`]+)`$", line)
        if heading:
            if current_flow:
                flows[current_flow["flowName"]] = current_flow
            current_flow = {
                "flowName": heading.group(1),
                "useWhen": [],
                "inputs": [],
                "inputSpec": [],
                "inputSemantics": {},
                "steps": [],
                "commandNames": [],
                "result": [],
                "notes": [],
            }
            current_section = None
            index += 1
            continue
        if current_flow is None:
            index += 1
            continue
        section_match = re.match(r"^- ([^:]+):$", line)
        if section_match:
            current_section = snake_case(section_match.group(1))
            index += 1
            continue
        bullet_match = re.match(r"^  - (.+)$", line)
        step_match = re.match(r"^  \d+\. (.+)$", line)
        if bullet_match and current_section:
            value = bullet_match.group(1).strip()
            if current_section == "use_when":
                current_flow["useWhen"].append(value)
            elif current_section == "inputs":
                current_flow["inputSpec"].append(value)
                current_flow["inputs"].extend(clean_contract_name(item) for item in extract_backticked_values(value))
            elif current_section == "result":
                current_flow["result"].append(value)
            elif current_section == "notes":
                current_flow["notes"].append(value)
        elif step_match:
            value = step_match.group(1).strip()
            current_flow["steps"].append(value)
            current_flow["commandNames"].extend(
                token for token in re.findall(r"`([^`]+)`", value) if "." in token
            )
        index += 1
    if current_flow:
        flows[current_flow["flowName"]] = current_flow
    for flow in flows.values():
        flow["inputs"] = sorted(set(flow["inputs"]))
        flow["inputSemantics"] = {
            input_name: flow_input_semantics(flow["flowName"], input_name)
            for input_name in flow["inputs"]
        }
        flow["commandNames"] = [name for idx, name in enumerate(flow["commandNames"]) if name not in flow["commandNames"][:idx]]
    return {
        "flowCount": len(flows),
        "payloadFamilies": copy_payload_families(),
        "selectorFamilies": copy_selector_families(),
        "flows": flows,
    }


def build_command_catalog(
    parsed_commands: list[ParsedCommand],
    operation_catalog: dict[str, Any],
) -> dict[str, Any]:
    operations = operation_catalog["operations"]
    method_index = operation_catalog["methodIndex"]
    commands: dict[str, Any] = {}
    for command in parsed_commands:
        lookup_key = f"{command.raw_method} {command.raw_path}"
        operation_id = method_index.get(lookup_key)
        if operation_id is None:
            raise KeyError(f"Could not resolve raw command for {command.name}: {lookup_key}")
        raw_meta = operations[operation_id]
        workflows = [value for value in command.workflows if value]
        verification_hints = []
        if raw_meta["method"] in {"POST", "PUT", "DELETE"} or raw_meta["actionMarker"]:
            verification_hints.append("verify mutation effect only when the raw response omits scoring-relevant fields")
        if raw_meta["safetyClass"] in {"destructive", "high_risk"}:
            verification_hints.append("confirm unique target before dispatch")
        input_bindings, unmapped_inputs = build_input_bindings(command.name, command, raw_meta)
        commands[command.name] = {
            "commandName": command.name,
            "operationId": operation_id,
            "rawMethod": command.raw_method,
            "rawPath": command.raw_path,
            "purpose": command.purpose,
            "inputs": command.inputs,
            "inputSpec": command.inputSpec,
            "workflowMembership": workflows,
            "safetyClass": raw_meta["safetyClass"],
            "technicalFlowFamily": raw_meta["technicalFlowFamily"],
            "verificationChecklist": verification_hints,
            "conformancePolicyKey": raw_meta["conformancePolicyKey"],
            "selectorFamily": selector_family_for_command(command.name),
            "inputSemantics": {
                input_name: command_input_semantics(command.name, input_name)
                for input_name in command.inputs
            },
            "inputBindings": input_bindings,
            "unmappedInputs": unmapped_inputs,
            "allowsBodyPassthrough": bool(raw_meta["requestBody"]),
            "notes": command.notes,
        }
    return {
        "commandCount": len(commands),
        "payloadFamilies": copy_payload_families(),
        "selectorFamilies": copy_selector_families(),
        "commands": commands,
    }


def build_conformance_policies() -> dict[str, Any]:
    return {
        "policyCount": 6,
        "policies": {
            "employee_access_mapping": {
                "title": "Employee Access Mapping",
                "summary": "Keep natural-language role mapping to user type and entitlement templates in one maintained policy layer.",
            },
            "department_module_activation": {
                "title": "Department Module Activation",
                "summary": "Sales module activation uses named module purchases, not boolean feature flags.",
            },
            "invoice_credit_note": {
                "title": "Invoice Credit Note",
                "summary": "Credit-note and correction flows require sandbox-confirmed payload and minimal verification.",
            },
            "travel_expense_payload": {
                "title": "Travel Expense Payload",
                "summary": "Base travel expense creation and row creation have schema quirks and should use dedicated row commands.",
            },
            "supplier_invoice_payment": {
                "title": "Supplier Invoice Payment",
                "summary": "Payment registration should prefer the action endpoint and keep payload narrow.",
            },
            "attachment_accounting": {
                "title": "Attachment Accounting",
                "summary": "Attachment-derived bookkeeping requires explicit provenance and extraction confidence handling.",
            },
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    spec = load_json(OPENAPI_PATH)
    desc_text = DESC_PATH.read_text(encoding="utf-8")

    operation_catalog = build_operation_catalog(spec)
    parsed_commands = parse_commands(desc_text)
    command_catalog = build_command_catalog(parsed_commands, operation_catalog)
    flow_catalog = parse_flows(desc_text)
    conformance_policies = build_conformance_policies()

    write_json(GENERATED_DIR / "operation_catalog.json", operation_catalog)
    write_json(GENERATED_DIR / "command_catalog.json", command_catalog)
    write_json(GENERATED_DIR / "flow_catalog.json", flow_catalog)
    write_json(GENERATED_DIR / "conformance_policies.json", conformance_policies)

    family_counter = Counter()
    for operation in operation_catalog["operations"].values():
        family_counter[operation["technicalFlowFamily"]] += 1

    print(
        json.dumps(
            {
                "operations": operation_catalog["operationCount"],
                "commands": command_catalog["commandCount"],
                "flows": flow_catalog["flowCount"],
                "distinctTechnicalFamilies": len(family_counter),
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Tripletex runtime catalogs from docs.")
    parser.parse_args()
    generate()


if __name__ == "__main__":
    main()
