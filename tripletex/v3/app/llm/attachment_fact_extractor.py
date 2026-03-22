from __future__ import annotations

import json
import logging
from typing import Any

from app.llm.json_payloads import load_json_payload
from app.llm.response_schemas import (
    attachment_facts_fallback_response_json_schema,
    attachment_facts_response_json_schema,
)
from app.raw.errors import RawExecutionError

from .gemini_client import GeminiClient


logger = logging.getLogger("tripletex_attachment_facts")


class AttachmentFactExtractor:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()

    def enrich(
        self,
        *,
        prompt: str,
        evidence: list[dict[str, Any]],
        attachment_media: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not evidence:
            return evidence
        prompt_package = self._build_prompt_package(
            prompt=prompt,
            evidence=evidence,
            attachment_media=attachment_media,
        )
        try:
            raw_response = self.client.generate(prompt_package)
        except RawExecutionError as exc:
            logger.warning(
                "attachment_fact_extraction.failed reason=transport message=%s details=%s",
                exc.message,
                exc.details,
            )
            return self._with_extraction_warning(
                evidence,
                "Structured attachment fact extraction failed; falling back to raw attachment evidence.",
            )

        normalized = self._normalize_response(raw_response, evidence=evidence)
        if normalized is None:
            logger.warning("attachment_fact_extraction.failed reason=invalid_json")
            return self._with_extraction_warning(
                evidence,
                "Structured attachment fact extraction returned invalid JSON; falling back to raw attachment evidence.",
            )

        normalized_by_id = {item["attachmentId"]: item for item in normalized}
        return [
            self._merge_attachment(
                attachment,
                normalized_by_id.get(str(attachment.get("attachmentId", "")).strip()),
            )
            for attachment in evidence
        ]

    def _build_prompt_package(
        self,
        *,
        prompt: str,
        evidence: list[dict[str, Any]],
        attachment_media: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "systemInstruction": (
                "You extract structured facts from Tripletex request attachments. "
                "Return exactly one JSON object with the top-level key attachments and no prose. "
                "Do not produce bridge JSON, commands, flows, or execution advice. "
                "For each attachment emit attachmentId, documentType, summary, factHints, structuredFacts, warnings, and confidence. "
                "factHints and warnings must be arrays of plain strings. "
                "structuredFacts must be a factual JSON object grounded in the attachment contents and extracted text only. "
                "Use null or omit fields when unknown instead of guessing. "
                "confidence must be a number between 0 and 1."
            ),
            "request": {
                "prompt": prompt,
                "attachments": [
                    {
                        "attachmentId": attachment.get("attachmentId"),
                        "filename": attachment.get("filename"),
                        "mimeType": attachment.get("mimeType"),
                        "extractedText": attachment.get("extractedText", ""),
                        "warnings": attachment.get("warnings", []),
                        "provenance": attachment.get("provenance", {}),
                    }
                    for attachment in evidence
                ],
            },
            "media": attachment_media,
            "context": {
                "targetSchema": {
                    "attachments": [
                        {
                            "attachmentId": "attachment_1",
                            "documentType": "supplier_invoice | receipt | travel_receipt | bank_payment_confirmation | contract | timesheet | other | unknown",
                            "summary": "short factual summary",
                            "factHints": ["plain string fact"],
                            "structuredFacts": {
                                "supplierName": "ACME AS",
                                "customerName": "Example Customer",
                                "invoiceNumber": "1001",
                                "documentNumber": "1001",
                                "organizationNumber": "123456789",
                                "bankAccount": "1234.56.78901",
                                "kid": "123456789",
                                "paymentReference": "INV-1001",
                                "currency": "NOK",
                                "grossAmount": 1250.0,
                                "netAmount": 1000.0,
                                "vatAmount": 250.0,
                                "invoiceDate": "2026-03-21",
                                "dueDate": "2026-04-21",
                                "paymentDate": "2026-03-22",
                                "descriptions": ["Consulting services"],
                                "routeHints": ["supplier_invoice.import_from_attachment"],
                                "missingCriticalFields": ["supplierName"],
                            },
                            "warnings": ["plain string warning"],
                            "confidence": 0.85,
                        }
                    ]
                }
            },
            "responseJsonSchema": attachment_facts_response_json_schema(),
            "fallbackResponseJsonSchema": attachment_facts_fallback_response_json_schema(),
        }

    def _normalize_response(
        self,
        payload: str,
        *,
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        try:
            data = load_json_payload(payload)
        except json.JSONDecodeError:
            return None
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("attachments")
        else:
            return None
        if not isinstance(items, list):
            return None
        known_ids = {
            str(item.get("attachmentId", "")).strip()
            for item in evidence
            if str(item.get("attachmentId", "")).strip()
        }
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            attachment_id = str(item.get("attachmentId", "")).strip()
            if not attachment_id or attachment_id not in known_ids:
                continue
            structured_facts = self._sanitize_json_value(item.get("structuredFacts"))
            if not isinstance(structured_facts, dict):
                structured_facts = {}
            fact_hints = self._string_list(item.get("factHints"))
            derived_fact_hints = self._derive_fact_hints(structured_facts)
            normalized.append(
                {
                    "attachmentId": attachment_id,
                    "documentType": self._safe_text(item.get("documentType")) or "unknown",
                    "summary": self._safe_text(item.get("summary")),
                    "factHints": self._dedupe_strings([*fact_hints, *derived_fact_hints]),
                    "structuredFacts": structured_facts,
                    "warnings": self._string_list(item.get("warnings")),
                    "confidence": self._safe_confidence(item.get("confidence")),
                }
            )
        return normalized

    def _merge_attachment(
        self,
        attachment: dict[str, Any],
        extracted: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = dict(attachment)
        if extracted is None:
            merged.setdefault("structuredFacts", {})
            merged.setdefault("factExtractionWarnings", [])
            return merged
        merged["documentType"] = extracted["documentType"]
        merged["structuredFacts"] = extracted["structuredFacts"]
        merged["factSummary"] = extracted["summary"]
        merged["factExtractionConfidence"] = extracted["confidence"]
        merged["extractedFactHints"] = extracted["factHints"]
        merged["factExtractionWarnings"] = extracted["warnings"]
        merged["provenance"] = {
            **dict(merged.get("provenance", {})),
            "factExtraction": "gemini_structured",
        }
        return merged

    def _with_extraction_warning(
        self,
        evidence: list[dict[str, Any]],
        warning: str,
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for attachment in evidence:
            item = dict(attachment)
            warnings = self._string_list(item.get("factExtractionWarnings"))
            warnings.append(warning)
            item["factExtractionWarnings"] = self._dedupe_strings(warnings)
            item.setdefault("structuredFacts", {})
            enriched.append(item)
        return enriched

    def _derive_fact_hints(self, structured_facts: dict[str, Any]) -> list[str]:
        hints: list[str] = []
        for key, value in structured_facts.items():
            hints.extend(self._fact_hints_for_value(key, value))
            if len(hints) >= 20:
                break
        return self._dedupe_strings(hints[:20])

    def _fact_hints_for_value(self, key: str, value: Any) -> list[str]:
        if isinstance(value, dict):
            hints: list[str] = []
            for nested_key, nested_value in value.items():
                hints.extend(self._fact_hints_for_value(f"{key}.{nested_key}", nested_value))
                if len(hints) >= 6:
                    break
            return hints[:6]
        if isinstance(value, list):
            hints: list[str] = []
            for item in value[:3]:
                text = self._safe_text(item)
                if text:
                    hints.append(f"{key}={text}")
            return hints
        if isinstance(value, (str, int, float, bool)):
            text = self._safe_text(value)
            if text:
                return [f"{key}={text}"]
        return []

    def _sanitize_json_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth >= 5:
            return None
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                key_text = self._safe_text(key)
                if not key_text:
                    continue
                sanitized[key_text] = self._sanitize_json_value(item, depth=depth + 1)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_json_value(item, depth=depth + 1) for item in value[:20]]
        text = self._safe_text(value)
        return text or None

    def _safe_text(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return text[:500]

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return self._dedupe_strings(self._safe_text(item) for item in value if self._safe_text(item))
        text = self._safe_text(value)
        return [text] if text else []

    def _dedupe_strings(self, values: Any) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in values:
            text = self._safe_text(raw)
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered

    def _safe_confidence(self, value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, numeric))
