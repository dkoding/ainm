from __future__ import annotations

from functools import lru_cache
import json
import logging
from typing import Any

from app.contracts import IntentDocument
from app.llm.json_payloads import load_json_payload
from app.llm.response_schemas import (
    intent_fallback_response_json_schema,
    intent_response_json_schema,
)
from app.raw import load_raw_catalog
from app.raw.errors import RawExecutionError
from app.wrapper import load_wrapper_catalog

from .gemini_client import GeminiClient


logger = logging.getLogger("tripletex_intent_extractor")


class IntentExtractor:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()
        self.wrapper_catalog = load_wrapper_catalog()
        self.raw_catalog = load_raw_catalog()

    def extract(
        self,
        *,
        prompt: str,
        evidence: list[dict[str, Any]],
        attachment_media: list[dict[str, Any]],
        current_date: str,
        timezone: str,
    ) -> IntentDocument:
        prompt_package = self._build_prompt_package(
            prompt=prompt,
            evidence=evidence,
            attachment_media=attachment_media,
            current_date=current_date,
            timezone=timezone,
        )
        try:
            raw_response = self.client.generate(prompt_package)
        except RawExecutionError as exc:
            logger.warning(
                "intent_extraction.failed reason=transport message=%s details=%s",
                exc.message,
                exc.details,
            )
            return self._fallback_intent(prompt=prompt, evidence=evidence)
        try:
            return self._normalize_response(raw_response, prompt=prompt, evidence=evidence)
        except RawExecutionError as exc:
            logger.warning(
                "intent_extraction.failed reason=invalid_json message=%s details=%s",
                exc.message,
                exc.details,
            )
            return self._fallback_intent(prompt=prompt, evidence=evidence)

    def _build_prompt_package(
        self,
        *,
        prompt: str,
        evidence: list[dict[str, Any]],
        attachment_media: list[dict[str, Any]],
        current_date: str,
        timezone: str,
    ) -> dict[str, Any]:
        return {
            "systemInstruction": (
                "You normalize Tripletex user requests into a structured intent contract. "
                "Return exactly one JSON object and no prose. "
                "The JSON must use contractVersion tripletex.intent.v1. "
                "Use the user's language understanding to infer the business intent, but emit only canonical JSON values. "
                "routeHints is optional but high-value: fill it with exact canonical route identifiers from the provided catalog when they fit the request. "
                "Only emit flowNames, commandNames, operationIds, technicalFlowFamilies, domains, subdomains, selectorFamilies, and payloadFamilies that exist in the provided catalog. "
                "Do not invent names. If uncertain, omit the hint instead of guessing. "
                "needsMutation should be true when the request changes Tripletex state. "
                "needsResolution should be true when the request needs a lookup, search, or read step. "
                "attachmentRelevant should be true when attachments materially affect the task. "
                "taskFamilies, targetResources, and operations should use short canonical snake_case or dotted identifiers, not free prose. "
                "intentSummary should be a short factual summary of the user's goal."
            ),
            "request": {
                "prompt": prompt,
                "currentDate": current_date,
                "timezone": timezone,
                "attachments": [
                    {
                        "attachmentId": attachment.get("attachmentId"),
                        "filename": attachment.get("filename"),
                        "mimeType": attachment.get("mimeType"),
                        "documentType": attachment.get("documentType"),
                        "factSummary": attachment.get("factSummary", ""),
                        "factHints": attachment.get("extractedFactHints", []),
                        "structuredFacts": attachment.get("structuredFacts", {}),
                        "warnings": attachment.get("factExtractionWarnings", []),
                    }
                    for attachment in evidence
                ],
            },
            "media": attachment_media,
            "context": {
                "targetSchema": {
                    "contractVersion": "tripletex.intent.v1",
                    "intentSummary": "register customer invoice payment",
                    "taskFamilies": ["invoice.payment"],
                    "targetResources": ["invoice", "payment"],
                    "operations": ["register_payment"],
                    "routeHints": {
                        "flowNames": ["invoice.register_payment"],
                        "commandNames": ["invoice.payment.create"],
                        "operationIds": ["InvoicePayment_payment"],
                        "technicalFlowFamilies": ["invoice.payment.create"],
                        "domains": ["invoice_payment"],
                        "subdomains": ["payment"],
                        "selectorFamilies": ["invoice_selector"],
                        "payloadFamilies": ["payment_spec"],
                    },
                    "needsMutation": True,
                    "needsResolution": True,
                    "attachmentRelevant": False,
                    "confidence": 0.86,
                    "ambiguities": ["plain string ambiguity"],
                    "missingData": ["plain string missing datum"],
                }
            },
            "referenceDocuments": [
                {
                    "name": "intent_route_catalog.json",
                    "mimeType": "application/json",
                    "instruction": (
                        "This is the canonical Tripletex route catalog for intent extraction. "
                        "Use it to ground routeHints and exact route names."
                    ),
                    "content": self._catalog_reference_document(),
                }
            ],
            "responseJsonSchema": intent_response_json_schema(),
            "fallbackResponseJsonSchema": intent_fallback_response_json_schema(),
        }

    def _normalize_response(
        self,
        payload: str,
        *,
        prompt: str,
        evidence: list[dict[str, Any]],
    ) -> IntentDocument:
        try:
            data = load_json_payload(payload)
        except (json.JSONDecodeError, SyntaxError, ValueError) as exc:
            raise RawExecutionError(message="Intent extractor output was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise RawExecutionError(message="Intent extractor output root must be a JSON object.")
        data = dict(data)
        data["contractVersion"] = "tripletex.intent.v1"
        route_hints = data.get("routeHints")
        if route_hints is None or not isinstance(route_hints, dict):
            data["routeHints"] = {}
        else:
            data["routeHints"] = dict(route_hints)
        data["intentSummary"] = self._safe_text(data.get("intentSummary")) or prompt
        data["taskFamilies"] = self._dedupe_strings(data.get("taskFamilies"))
        data["targetResources"] = self._dedupe_strings(data.get("targetResources"))
        data["operations"] = self._dedupe_strings(data.get("operations"))
        data["ambiguities"] = self._dedupe_strings(data.get("ambiguities"))
        data["missingData"] = self._dedupe_strings(data.get("missingData"))
        data["confidence"] = self._safe_confidence(data.get("confidence"))
        data["needsMutation"] = self._safe_bool(data.get("needsMutation"))
        data["needsResolution"] = self._safe_bool(data.get("needsResolution"))
        data["attachmentRelevant"] = self._safe_bool(data.get("attachmentRelevant"))
        route_hints = data["routeHints"]
        route_hints["flowNames"] = self._known_names(route_hints.get("flowNames"), self.wrapper_catalog.flows)
        route_hints["commandNames"] = self._known_names(route_hints.get("commandNames"), self.wrapper_catalog.commands)
        route_hints["operationIds"] = self._known_names(route_hints.get("operationIds"), self.raw_catalog.operations)
        route_hints["technicalFlowFamilies"] = self._known_technical_families(route_hints.get("technicalFlowFamilies"))
        route_hints["domains"] = self._known_names(route_hints.get("domains"), self._known_domains())
        route_hints["subdomains"] = self._known_names(route_hints.get("subdomains"), self._known_subdomains())
        route_hints["selectorFamilies"] = self._known_names(
            route_hints.get("selectorFamilies"),
            self.wrapper_catalog.selector_families,
        )
        route_hints["payloadFamilies"] = self._known_names(
            route_hints.get("payloadFamilies"),
            self.wrapper_catalog.payload_families,
        )
        self._merge_attachment_route_hints(route_hints, evidence)
        return IntentDocument.model_validate(data)

    def _fallback_intent(self, *, prompt: str, evidence: list[dict[str, Any]]) -> IntentDocument:
        route_hints: dict[str, Any] = {
            "flowNames": [],
            "commandNames": [],
            "operationIds": [],
            "technicalFlowFamilies": [],
            "domains": [],
            "subdomains": [],
            "selectorFamilies": [],
            "payloadFamilies": [],
        }
        self._merge_attachment_route_hints(route_hints, evidence)
        attachment_relevant = any(route_hints["flowNames"] or route_hints["commandNames"] or route_hints["operationIds"] or evidence)
        return IntentDocument.model_validate(
            {
                "contractVersion": "tripletex.intent.v1",
                "intentSummary": prompt,
                "taskFamilies": [],
                "targetResources": [],
                "operations": [],
                "routeHints": route_hints,
                "attachmentRelevant": attachment_relevant,
                "ambiguities": [],
                "missingData": [],
            }
        )

    @lru_cache(maxsize=1)
    def _catalog_reference_document(self) -> str:
        flows: list[dict[str, Any]] = []
        for flow_name in sorted(self.wrapper_catalog.flows):
            flow = self.wrapper_catalog.get_flow(flow_name)
            selector_families: set[str] = set()
            payload_families: set[str] = set()
            for semantic in (flow.get("inputSemantics") or {}).values():
                if not isinstance(semantic, dict):
                    continue
                selector_family = str(semantic.get("selectorFamily", "")).strip()
                if selector_family:
                    selector_families.add(selector_family)
                payload_family = str(semantic.get("payloadFamily", "")).strip()
                if payload_family:
                    payload_families.add(payload_family)
                item_family = str(semantic.get("itemFamily", "")).strip()
                if item_family:
                    payload_families.add(item_family)
            flows.append(
                {
                    "flowName": flow_name,
                    "commandNames": list(flow.get("commandNames", [])),
                    "useWhen": list(flow.get("useWhen", [])),
                    "selectorFamilies": sorted(selector_families),
                    "payloadFamilies": sorted(payload_families),
                }
            )
        commands: list[dict[str, Any]] = []
        for command_name in sorted(self.wrapper_catalog.commands):
            command = self.wrapper_catalog.get_command(command_name)
            payload_families: set[str] = set()
            for semantic in (command.get("inputSemantics") or {}).values():
                if not isinstance(semantic, dict):
                    continue
                payload_family = str(semantic.get("payloadFamily", "")).strip()
                if payload_family:
                    payload_families.add(payload_family)
                item_family = str(semantic.get("itemFamily", "")).strip()
                if item_family:
                    payload_families.add(item_family)
            commands.append(
                {
                    "commandName": command_name,
                    "operationId": command.get("operationId"),
                    "technicalFlowFamily": command.get("technicalFlowFamily"),
                    "workflowMembership": list(command.get("workflowMembership", [])),
                    "purpose": command.get("purpose", ""),
                    "selectorFamily": command.get("selectorFamily"),
                    "payloadFamilies": sorted(payload_families),
                    "safetyClass": command.get("safetyClass"),
                }
            )
        operations = [
            {
                "operationId": operation_id,
                "domain": operation.get("domain"),
                "subdomain": operation.get("subdomain"),
                "technicalFlowFamilies": list(operation.get("technicalFlowFamilies", [])),
                "semanticAliases": list(operation.get("semanticAliases", [])),
                "purpose": operation.get("purpose", ""),
                "method": operation.get("method"),
                "path": operation.get("path"),
            }
            for operation_id, operation in sorted(self.raw_catalog.operations.items())
        ]
        document = {
            "catalogVersion": "tripletex.intent_catalog.v1",
            "flowCount": len(flows),
            "commandCount": len(commands),
            "operationCount": len(operations),
            "flows": flows,
            "commands": commands,
            "operations": operations,
        }
        return json.dumps(document, ensure_ascii=False, separators=(",", ":"))

    def _merge_attachment_route_hints(self, route_hints: dict[str, Any], evidence: list[dict[str, Any]]) -> None:
        flow_names = list(route_hints.get("flowNames") or [])
        command_names = list(route_hints.get("commandNames") or [])
        operation_ids = list(route_hints.get("operationIds") or [])
        domains = list(route_hints.get("domains") or [])
        for attachment in evidence:
            document_type = self._safe_text(attachment.get("documentType"))
            if document_type and document_type in self._known_domains():
                domains.append(document_type)
            structured_facts = attachment.get("structuredFacts")
            if not isinstance(structured_facts, dict):
                continue
            route_values = structured_facts.get("routeHints")
            for route_name in self._dedupe_strings(route_values):
                if route_name in self.wrapper_catalog.flows:
                    flow_names.append(route_name)
                elif route_name in self.wrapper_catalog.commands:
                    command_names.append(route_name)
                elif route_name in self.raw_catalog.operations:
                    operation_ids.append(route_name)
        route_hints["flowNames"] = self._dedupe_strings(flow_names)
        route_hints["commandNames"] = self._dedupe_strings(command_names)
        route_hints["operationIds"] = self._dedupe_strings(operation_ids)
        route_hints["domains"] = self._known_names(domains, self._known_domains())

    def _known_domains(self) -> set[str]:
        return {
            value
            for value in (
                str(operation.get("domain", "")).strip()
                for operation in self.raw_catalog.operations.values()
            )
            if value
        }

    def _known_subdomains(self) -> set[str]:
        return {
            value
            for value in (
                str(operation.get("subdomain", "")).strip()
                for operation in self.raw_catalog.operations.values()
            )
            if value
        }

    def _known_technical_families(self, values: Any) -> list[str]:
        known = {
            family
            for operation in self.raw_catalog.operations.values()
            for family in operation.get("technicalFlowFamilies", [])
            if isinstance(family, str) and family
        }
        known.update(
            family
            for command in self.wrapper_catalog.commands.values()
            for family in [command.get("technicalFlowFamily")]
            if isinstance(family, str) and family
        )
        return self._known_names(values, known)

    def _known_names(self, values: Any, known: dict[str, Any] | set[str]) -> list[str]:
        known_names = set(known.keys()) if isinstance(known, dict) else set(known)
        return [value for value in self._dedupe_strings(values) if value in known_names]

    def _dedupe_strings(self, values: Any) -> list[str]:
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return []
        seen: set[str] = set()
        result: list[str] = []
        for item in values:
            text = self._safe_text(item)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _safe_text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _safe_bool(self, value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        return None

    def _safe_confidence(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        return None
