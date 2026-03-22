from __future__ import annotations

import json
from typing import Any

from app.benchmark.models import FamilyCandidate, NormalizedRequest
from app.benchmark.registry import TaskRegistry
from app.llm.gemini_client import GeminiClient
from app.llm.json_payloads import load_json_payload
from app.raw.errors import RawExecutionError


class FamilySelector:
    def __init__(
        self,
        registry: TaskRegistry | None = None,
        client: GeminiClient | None = None,
    ) -> None:
        self.registry = registry or TaskRegistry()
        self.client = client or GeminiClient()

    def select(self, request: NormalizedRequest, *, limit: int = 5) -> tuple[FamilyCandidate, ...]:
        prompt_package = self._build_prompt_package(request)
        raw_response = self.client.generate(prompt_package)
        try:
            payload = load_json_payload(raw_response)
        except json.JSONDecodeError as exc:
            raise RawExecutionError(message="Benchmark family selector returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise RawExecutionError(message="Benchmark family selector root must be a JSON object.")
        items = payload.get("candidates")
        if not isinstance(items, list):
            selected = payload.get("selectedFamilyId")
            if isinstance(selected, str) and selected.strip():
                items = [{"familyId": selected.strip(), "confidence": payload.get("confidence", 0.0), "reasons": []}]
            else:
                return ()
        candidates: list[FamilyCandidate] = []
        valid_ids = set(self.registry.list_family_ids())
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            family_id = str(item.get("familyId") or "").strip()
            if family_id not in valid_ids:
                continue
            confidence = self._coerce_confidence(item.get("confidence"))
            score = confidence * 10.0
            reasons = self._string_list(item.get("reasons"))
            matched_fields = self._string_list(item.get("matchedFields"))
            candidates.append(
                FamilyCandidate(
                    family_id=family_id,
                    score=round(score, 3),
                    confidence=confidence,
                    matched_terms=(),
                    matched_slots=tuple(matched_fields),
                    reasons=tuple(reasons),
                )
            )
        candidates.sort(key=lambda candidate: (-candidate.confidence, -candidate.score, candidate.family_id))
        return tuple(candidates[:limit])

    def _build_prompt_package(self, request: NormalizedRequest) -> dict[str, Any]:
        return {
            "systemInstruction": (
                "You are the Tripletex V4 task-family selector. "
                "Return exactly one JSON object and no prose. "
                "Choose the best matching task families from the provided canonical family list. "
                "Do not invent family ids. "
                "Handle any prompt language variation yourself; the code only gives canonical family definitions. "
                "Use attachments, structured facts, and summaries when they are relevant. "
                "Return a candidates array sorted best-first. "
                "Each candidate must contain familyId, confidence, reasons, and matchedFields. "
            ),
            "request": {
                "prompt": request.prompt,
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
                    }
                    for attachment in request.attachments
                ],
            },
            "context": {
                "families": [
                    {
                        "familyId": manifest.family_id,
                        "category": manifest.category,
                        "summary": manifest.summary,
                        "requiresAttachment": manifest.requires_attachment,
                        "attachmentDocumentTypes": list(manifest.attachment_document_types),
                        "requiredSlots": [slot.name for slot in manifest.required_slots],
                        "optionalSlots": [slot.name for slot in manifest.optional_slots],
                    }
                    for manifest in self.registry.all()
                ],
                "targetSchema": {
                    "candidates": [
                        {
                            "familyId": "employee.create_basic",
                            "confidence": 0.86,
                            "reasons": ["The prompt asks to create a new employee record."],
                            "matchedFields": ["first_name", "last_name"],
                        }
                    ]
                },
            },
        }

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
