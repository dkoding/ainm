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
        self.repair_engine = repair_engine or RepairEngine(client=self.client, validator=self.validator)

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
            return self.validator.validate(raw_response)
        except RawExecutionError as exc:
            if "valid JSON" in exc.message or "bridge schema" in exc.message:
                return self.repair_engine.repair(raw_response, [exc.message])
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
        return self.validator.validate(parsed)
