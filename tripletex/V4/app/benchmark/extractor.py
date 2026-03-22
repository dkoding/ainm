from __future__ import annotations

import json
from typing import Any

from app.benchmark.models import BenchmarkRouteContract, FamilyExtraction, NormalizedRequest, TaskFamilyManifest
from app.llm.gemini_client import GeminiClient
from app.llm.json_payloads import load_json_payload
from app.raw.errors import RawExecutionError
from app.semantic_contract import canonicalize_payload_value, canonicalize_selector_value, selector_family_for_entity
from app.utils import normalize_key
from app.wrapper.helpers import coerce_int_like, match_name


class BenchmarkSlotExtractor:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()

    def extract(
        self,
        *,
        manifest: TaskFamilyManifest,
        route_contract: BenchmarkRouteContract,
        request: NormalizedRequest,
        current_date: str,
        timezone: str,
    ) -> FamilyExtraction:
        prompt_package = self._build_prompt_package(
            manifest=manifest,
            route_contract=route_contract,
            request=request,
            current_date=current_date,
            timezone=timezone,
        )
        raw_response = self.client.generate(prompt_package)
        try:
            data = load_json_payload(raw_response)
        except json.JSONDecodeError as exc:
            raise RawExecutionError(message="Benchmark slot extractor returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise RawExecutionError(message="Benchmark slot extractor root must be a JSON object.")
        family_id = str(data.get("familyId") or manifest.family_id).strip()
        if family_id != manifest.family_id:
            raise RawExecutionError(
                message=f"Benchmark slot extractor returned {family_id}, expected {manifest.family_id}."
            )
        inputs = self._normalize_inputs(
            data.get("inputs"),
            route_contract=route_contract,
        )
        self._apply_manifest_defaults(
            inputs,
            manifest=manifest,
            route_contract=route_contract,
            request=request,
        )
        missing_required_inputs = self._missing_required_inputs(route_contract, inputs)
        warnings = self._string_list(data.get("warnings"))
        confidence = self._coerce_confidence(data.get("confidence"))
        return FamilyExtraction(
            family_id=manifest.family_id,
            route_kind=route_contract.route_kind,
            route_name=route_contract.route_name,
            inputs=inputs,
            missing_required_inputs=missing_required_inputs,
            warnings=tuple(warnings),
            confidence=confidence,
        )

    def _build_prompt_package(
        self,
        *,
        manifest: TaskFamilyManifest,
        route_contract: BenchmarkRouteContract,
        request: NormalizedRequest,
        current_date: str,
        timezone: str,
    ) -> dict[str, Any]:
        attachment_rule = (
            "This family requires an uploaded attachment. If exactly one attachment is provided, prefer that attachmentId. "
            if manifest.requires_attachment
            else "Do not invent attachment ids."
        )
        return {
            "systemInstruction": (
                "You are the Tripletex V4 benchmark slot extractor. "
                "Return exactly one JSON object and no prose. "
                "Your job is only to fill structured inputs for one already-selected task family and route. "
                "Do not emit flows, commands, raw operation plans, explanations, markdown, or bridge JSON. "
                "Use only the legal route inputs listed in context.routeContract.legalInputs. "
                "Obey context.routeContract.requiredInputGroups. If a required group is not grounded in the prompt or attachments, leave the input out and list it in missingRequiredInputs. "
                "Use ISO dates, booleans as JSON booleans, integers as JSON numbers, and arrays as JSON arrays. "
                "For selector inputs, emit selector objects using only the allowed selector fields from context.selectorFamilies. "
                "For payload inputs and row arrays, emit only the allowed fields from context.payloadFamilies. "
                "For selector_or_create_payload inputs, emit a selector object when existing-record lookup is intended, or a create payload object using only the listed create payload inputs when the task is creating the related record. "
                "Never invent ids. "
                "Prefer request.attachments[].structuredFacts, summaries, and factHints over raw OCR-style text. "
                "Do not guess values that are absent from the evidence. "
                f"{attachment_rule}"
            ),
            "request": {
                "prompt": request.prompt,
                "currentDate": current_date,
                "timezone": timezone,
                "attachments": [
                    {
                        "attachmentId": attachment.attachment_id,
                        "filename": attachment.filename,
                        "mimeType": attachment.mime_type,
                        "documentType": attachment.document_type,
                        "summary": attachment.summary,
                        "factHints": list(attachment.fact_hints),
                        "structuredFacts": attachment.structured_facts,
                        "warnings": list(attachment.warnings),
                        "extractedText": attachment.extracted_text[:3000],
                    }
                    for attachment in request.attachments
                ],
            },
            "context": {
                "family": {
                    "familyId": manifest.family_id,
                    "category": manifest.category,
                    "summary": manifest.summary,
                    "requiresAttachment": manifest.requires_attachment,
                },
                "routeContract": {
                    "routeKind": route_contract.route_kind,
                    "routeName": route_contract.route_name,
                    "legalInputs": list(route_contract.legal_inputs),
                    "requiredInputGroups": [list(group) for group in route_contract.required_input_groups],
                    "inputSemantics": route_contract.input_semantics,
                    "createPayloadContracts": route_contract.create_payload_contracts,
                    "openapiHints": route_contract.openapi_hints,
                    "notes": list(route_contract.notes),
                },
                "selectorFamilies": route_contract.selector_families,
                "payloadFamilies": route_contract.payload_families,
                "targetSchema": {
                    "familyId": manifest.family_id,
                    "inputs": {name: "<value>" for name in route_contract.legal_inputs},
                    "missingRequiredInputs": ["plain string input name or one-of group description"],
                    "warnings": ["plain string warning"],
                    "confidence": 0.82,
                },
            },
        }

    def _normalize_inputs(
        self,
        payload: Any,
        *,
        route_contract: BenchmarkRouteContract,
    ) -> dict[str, object]:
        if not isinstance(payload, dict):
            return {}
        result: dict[str, object] = {}
        legal_inputs = list(route_contract.legal_inputs)
        for key, value in payload.items():
            resolved_key = match_name(str(key), legal_inputs) or self._lookup_legal_input(str(key), legal_inputs)
            if not resolved_key:
                continue
            semantic = route_contract.input_semantics.get(resolved_key, {})
            normalized_value = self._normalize_value(
                resolved_key,
                value,
                semantic=semantic,
                route_contract=route_contract,
            )
            if self._is_empty_value(normalized_value):
                continue
            result[resolved_key] = normalized_value
        return result

    def _normalize_value(
        self,
        input_name: str,
        value: Any,
        *,
        semantic: dict[str, Any],
        route_contract: BenchmarkRouteContract,
    ) -> object:
        kind = semantic.get("kind")
        if kind == "selector":
            selector_family = semantic.get("selectorFamily")
            return canonicalize_selector_value(selector_family if isinstance(selector_family, str) else None, value)
        if kind == "selector_or_create_payload":
            return self._normalize_selector_or_create_payload(input_name, value, semantic, route_contract)
        if kind == "payload":
            payload_family = semantic.get("payloadFamily")
            return canonicalize_payload_value(payload_family if isinstance(payload_family, str) else None, value)
        if kind == "array_payload":
            payload_family = semantic.get("itemFamily")
            items = value if isinstance(value, list) else [value]
            return [
                canonicalize_payload_value(payload_family if isinstance(payload_family, str) else None, item)
                for item in items
                if not self._is_empty_value(item)
            ]
        if kind == "selector_field" and input_name.endswith("_id"):
            if isinstance(value, dict) and "id" in value:
                return coerce_int_like(value["id"], field_name=input_name)
            return self._coerce_scalar(input_name, value, route_contract)
        return self._coerce_scalar(input_name, value, route_contract)

    def _normalize_selector_or_create_payload(
        self,
        input_name: str,
        value: Any,
        semantic: dict[str, Any],
        route_contract: BenchmarkRouteContract,
    ) -> object:
        if not isinstance(value, dict):
            return value
        selector_family = semantic.get("selectorFamily")
        if isinstance(selector_family, str):
            selector_value = canonicalize_selector_value(selector_family, value)
            selector_allowed = {
                normalize_key(field)
                for field in route_contract.selector_families.get(selector_family, {}).get("allowedFields", [])
            }
            if selector_allowed and all(normalize_key(str(key)) in selector_allowed for key in selector_value):
                return selector_value
        create_contract = route_contract.create_payload_contracts.get(input_name)
        if not isinstance(create_contract, dict):
            return value
        create_inputs = create_contract.get("legalInputs")
        if not isinstance(create_inputs, (list, tuple)):
            return value
        normalized: dict[str, object] = {}
        for key, item in value.items():
            resolved = match_name(str(key), list(create_inputs)) or self._lookup_legal_input(str(key), list(create_inputs))
            if not resolved:
                continue
            nested_semantic = {}
            semantics = create_contract.get("inputSemantics")
            if isinstance(semantics, dict):
                nested_candidate = semantics.get(resolved)
                if isinstance(nested_candidate, dict):
                    nested_semantic = nested_candidate
            normalized[resolved] = self._normalize_create_payload_value(resolved, item, nested_semantic)
        return normalized or value

    def _normalize_create_payload_value(self, input_name: str, value: Any, semantic: dict[str, Any]) -> object:
        kind = semantic.get("kind")
        if kind == "reference" or input_name.endswith("_ref"):
            selector_family = selector_family_for_entity(input_name[:-4])
            if selector_family and isinstance(value, dict):
                return canonicalize_selector_value(selector_family, value)
        return value

    def _coerce_scalar(
        self,
        input_name: str,
        value: Any,
        route_contract: BenchmarkRouteContract,
    ) -> object:
        hint = route_contract.openapi_hints.get(input_name, {})
        hint_type = str(hint.get("type") or "").strip().lower()
        if isinstance(value, str):
            stripped = value.strip()
            if hint_type == "boolean":
                boolean = self._coerce_bool(stripped)
                if boolean is not None:
                    return boolean
            if hint_type == "integer" and stripped.isdigit():
                return int(stripped)
            if hint_type == "number":
                number = self._coerce_number(stripped)
                if number is not None:
                    return number
            heuristic_boolean = self._coerce_bool(stripped)
            if heuristic_boolean is not None and input_name.startswith(("is_", "has_", "use_", "only_")):
                return heuristic_boolean
            return stripped
        if hint_type == "integer" and isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    def _apply_manifest_defaults(
        self,
        inputs: dict[str, object],
        *,
        manifest: TaskFamilyManifest,
        route_contract: BenchmarkRouteContract,
        request: NormalizedRequest,
    ) -> None:
        if not manifest.requires_attachment:
            return
        if "attachment_id" not in route_contract.legal_inputs or inputs.get("attachment_id") is not None:
            return
        if len(request.attachments) == 1:
            inputs["attachment_id"] = request.attachments[0].attachment_id

    def _missing_required_inputs(
        self,
        route_contract: BenchmarkRouteContract,
        inputs: dict[str, object],
    ) -> tuple[str, ...]:
        missing: list[str] = []
        for group in route_contract.required_input_groups:
            if any(self._has_meaningful_value(inputs.get(name)) for name in group):
                continue
            if len(group) == 1:
                missing.append(group[0])
            else:
                missing.append("one of: " + ", ".join(group))
        return tuple(missing)

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _coerce_confidence(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return max(0.0, min(float(value), 1.0))
        if isinstance(value, str):
            try:
                parsed = float(value.strip())
            except ValueError:
                return 0.0
            return max(0.0, min(parsed, 1.0))
        return 0.0

    def _coerce_bool(self, value: str) -> bool | None:
        lowered = value.lower()
        if lowered in {"true", "yes", "ja", "y", "1"}:
            return True
        if lowered in {"false", "no", "nei", "n", "0"}:
            return False
        return None

    def _coerce_number(self, value: str) -> int | float | None:
        cleaned = value.replace(" ", "").replace(",", ".")
        try:
            parsed = float(cleaned)
        except ValueError:
            return None
        if parsed.is_integer():
            return int(parsed)
        return parsed

    def _lookup_legal_input(self, candidate: str, legal_inputs: list[str]) -> str | None:
        target = normalize_key(candidate)
        for legal_input in legal_inputs:
            if normalize_key(legal_input) == target:
                return legal_input
        return None

    def _is_empty_value(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, dict, set)):
            return not value
        return False

    def _has_meaningful_value(self, value: Any) -> bool:
        return not self._is_empty_value(value)
