from __future__ import annotations

import json
from typing import Any

from app.contracts import LLMBridgeDocument, SolveRequest
from app.llm.attachment_evidence_builder import AttachmentEvidenceBuilder
from app.llm.context_catalog import ContextCatalog
from app.llm.gemini_client import GeminiClient
from app.llm.prompt_builder import PromptBuilder
from app.llm.repair_engine import RepairEngine
from app.llm.response_validator import ResponseValidator
from app.raw.errors import RawExecutionError


class LLMPlanner:
    def __init__(
        self,
        *,
        evidence_builder: AttachmentEvidenceBuilder | None = None,
        context_catalog: ContextCatalog | None = None,
        prompt_builder: PromptBuilder | None = None,
        client: GeminiClient | None = None,
        validator: ResponseValidator | None = None,
        repair_engine: RepairEngine | None = None,
    ) -> None:
        self.evidence_builder = evidence_builder or AttachmentEvidenceBuilder()
        self.context_catalog = context_catalog or ContextCatalog()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.client = client or GeminiClient()
        self.validator = validator or ResponseValidator()
        self.repair_engine = repair_engine or RepairEngine(client=self.client)

    def plan(self, request: SolveRequest, *, current_date: str, timezone: str, request_id: str) -> LLMBridgeDocument:
        direct = self._maybe_validate_direct_json(request.prompt)
        if direct is not None:
            return direct
        evidence = self.evidence_builder.build(request.files)
        context_slice = self.context_catalog.build_slice(request.prompt)
        prompt_package = self.prompt_builder.build(
            prompt=request.prompt,
            evidence=evidence,
            current_date=current_date,
            timezone=timezone,
            context_slice=context_slice,
        )
        try:
            raw_response = self.client.generate(prompt_package)
        except RawExecutionError:
            raise
        try:
            return self._validate_with_request_defaults(
                raw_response,
                prompt=request.prompt,
                current_date=current_date,
                timezone=timezone,
                request_id=request_id,
                attachment_count=len(request.files),
            )
        except RawExecutionError as exc:
            repair_errors = [exc.message]
            detailed_errors = exc.details.get("errors")
            if isinstance(detailed_errors, list):
                for item in detailed_errors[:8]:
                    repair_errors.append(json.dumps(item, ensure_ascii=False))
            if isinstance(raw_response, str):
                repaired = self.repair_engine.repair(raw_response, repair_errors)
                return self._validate_with_request_defaults(
                    repaired,
                    prompt=request.prompt,
                    current_date=current_date,
                    timezone=timezone,
                    request_id=request_id,
                    attachment_count=len(request.files),
                )
            raise

    def _maybe_validate_direct_json(self, prompt: str) -> LLMBridgeDocument | None:
        candidate = prompt.strip()
        if not candidate.startswith("{"):
            return None
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if parsed.get("contractVersion") != "tripletex.llm_bridge.v1":
            return None
        return self._validate_with_request_defaults(
            parsed,
            prompt=prompt,
            current_date="",
            timezone="",
            request_id="",
            attachment_count=0,
        )

    def _validate_with_request_defaults(
        self,
        payload: str | dict[str, Any],
        *,
        prompt: str,
        current_date: str,
        timezone: str,
        request_id: str,
        attachment_count: int,
    ) -> LLMBridgeDocument:
        candidate = self._prepare_candidate(
            payload,
            prompt=prompt,
            current_date=current_date,
            timezone=timezone,
            request_id=request_id,
            attachment_count=attachment_count,
        )
        return self.validator.validate(candidate)

    def _prepare_candidate(
        self,
        payload: str | dict[str, Any],
        *,
        prompt: str,
        current_date: str,
        timezone: str,
        request_id: str,
        attachment_count: int,
    ) -> str | dict[str, Any]:
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return payload
        else:
            data = dict(payload)
        if not isinstance(data, dict):
            return payload
        data["__tripletex_defaults"] = {
            "prompt": prompt,
            "currentDate": current_date,
            "timezone": timezone,
            "requestId": request_id,
            "attachmentCount": attachment_count,
        }
        return data
