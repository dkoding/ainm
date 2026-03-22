from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.benchmark.bridge_builder import BenchmarkBridgeBuilder
from app.benchmark.classifier import FamilyClassifier, normalize_text, tokenize_text
from app.benchmark.executor_registry import ExecutorRegistry
from app.benchmark.extractor import BenchmarkSlotExtractor
from app.benchmark.models import AttachmentProfile, BenchmarkAnalysis, NormalizedRequest
from app.benchmark.registry import TaskRegistry
from app.benchmark.route_contract import RouteContractBuilder
from app.benchmark.selector import FamilySelector
from app.contracts import LLMBridgeDocument, SolveRequest
from app.llm.attachment_evidence_builder import AttachmentEvidenceBuilder
from app.llm.attachment_fact_extractor import AttachmentFactExtractor
from app.llm.gemini_client import GeminiClient
from app.raw.errors import RawExecutionError


class BenchmarkRuntime:
    def __init__(
        self,
        *,
        registry: TaskRegistry | None = None,
        selector: FamilySelector | None = None,
        classifier: FamilyClassifier | None = None,
        executors: ExecutorRegistry | None = None,
        evidence_builder: AttachmentEvidenceBuilder | None = None,
        attachment_fact_extractor: AttachmentFactExtractor | None = None,
        route_contract_builder: RouteContractBuilder | None = None,
        slot_extractor: BenchmarkSlotExtractor | None = None,
        bridge_builder: BenchmarkBridgeBuilder | None = None,
        client: GeminiClient | None = None,
    ) -> None:
        self.registry = registry or TaskRegistry()
        shared_client = client or GeminiClient()
        self.selector = selector or FamilySelector(self.registry, client=shared_client)
        self.classifier = classifier or FamilyClassifier(self.registry)
        self.executors = executors or ExecutorRegistry()
        self.evidence_builder = evidence_builder or AttachmentEvidenceBuilder()
        self.attachment_fact_extractor = attachment_fact_extractor or AttachmentFactExtractor(client=shared_client)
        self.route_contract_builder = route_contract_builder or RouteContractBuilder()
        self.slot_extractor = slot_extractor or BenchmarkSlotExtractor(client=shared_client)
        self.bridge_builder = bridge_builder or BenchmarkBridgeBuilder()

    def analyze(self, request: SolveRequest) -> BenchmarkAnalysis:
        normalized_request = self.prepare_request(request)
        notes: list[str] = []
        candidates = self._select_candidates(normalized_request, notes=notes)
        selected = candidates[0] if candidates else None
        manifest = self.registry.get(selected.family_id) if selected else None
        route_contract = self.route_contract_builder.build(manifest) if manifest is not None else None
        supported_by_executor = route_contract is not None or self.executors.supports(selected.family_id if selected else None)
        if normalized_request.has_attachments:
            notes.append("attachments_prepared")
        else:
            notes.append("no_attachments")
        if selected is None:
            notes.append("no_family_match")
        elif supported_by_executor:
            notes.append("benchmark_route_available")
        else:
            notes.append("legacy_fallback_required")
        if manifest and manifest.requires_attachment and not normalized_request.has_attachments:
            notes.append("required_attachment_missing")
        return BenchmarkAnalysis(
            normalized_request=normalized_request,
            selected_family_id=selected.family_id if selected else None,
            selected_route_kind=route_contract.route_kind if route_contract else None,
            selected_route_name=route_contract.route_name if route_contract else None,
            selected_flow_name=manifest.preferred_flow_name if manifest else None,
            selected_executor_name=manifest.executor_name if manifest else None,
            supported_by_executor=supported_by_executor,
            execution_mode="benchmark_candidate" if supported_by_executor else "legacy_fallback",
            candidates=candidates,
            notes=tuple(notes),
        )

    def prepare_bridge(
        self,
        request: SolveRequest,
        *,
        current_date: str,
        timezone: str,
        request_id: str,
    ) -> tuple[BenchmarkAnalysis, LLMBridgeDocument | None]:
        analysis = self.analyze(request)
        if not analysis.selected_family_id:
            return analysis, None
        manifest = self.registry.get(analysis.selected_family_id)
        if manifest is None:
            return replace(analysis, notes=analysis.notes + ("unknown_family",)), None
        route_contract = self.route_contract_builder.build(manifest)
        if route_contract is None:
            return replace(analysis, notes=analysis.notes + ("missing_route_contract",)), None
        if manifest.requires_attachment and not analysis.normalized_request.has_attachments:
            return replace(
                analysis,
                execution_mode="legacy_fallback",
                notes=analysis.notes + ("required_attachment_missing",),
            ), None
        try:
            extraction = self.slot_extractor.extract(
                manifest=manifest,
                route_contract=route_contract,
                request=analysis.normalized_request,
                current_date=current_date,
                timezone=timezone,
            )
        except RawExecutionError:
            return replace(
                analysis,
                execution_mode="legacy_fallback",
                notes=analysis.notes + ("slot_extraction_failed",),
            ), None
        if extraction.missing_required_inputs:
            return replace(
                analysis,
                execution_mode="legacy_fallback",
                notes=analysis.notes + ("benchmark_inputs_incomplete",),
            ), None
        if self._should_fallback_on_confidence(analysis, extraction.confidence):
            return replace(
                analysis,
                execution_mode="legacy_fallback",
                notes=analysis.notes + ("benchmark_confidence_too_low",),
            ), None
        try:
            bridge = self.bridge_builder.build(
                manifest=manifest,
                route_contract=route_contract,
                extraction=extraction,
                request=analysis.normalized_request,
                request_id=request_id,
                current_date=current_date,
                timezone=timezone,
            )
        except RawExecutionError:
            return replace(
                analysis,
                execution_mode="legacy_fallback",
                notes=analysis.notes + ("benchmark_bridge_invalid",),
            ), None
        return replace(
            analysis,
            selected_route_kind=route_contract.route_kind,
            selected_route_name=route_contract.route_name,
            execution_mode="benchmark_bridge",
            supported_by_executor=True,
            notes=analysis.notes + ("benchmark_bridge_ready",),
        ), bridge

    def prepare_request(self, request: SolveRequest) -> NormalizedRequest:
        evidence = self.evidence_builder.build(request.files)
        attachment_media = tuple(
            {
                "attachmentId": f"attachment_{index}",
                "filename": file.filename,
                "mimeType": file.mime_type,
                "contentBase64": file.content_base64,
            }
            for index, file in enumerate(request.files, start=1)
        )
        if evidence:
            evidence = self.attachment_fact_extractor.enrich(
                prompt=request.prompt,
                evidence=evidence,
                attachment_media=list(attachment_media),
            )
        attachments = tuple(self._to_attachment_profile(item) for item in evidence)
        return NormalizedRequest(
            prompt=request.prompt,
            prompt_normalized=normalize_text(request.prompt),
            prompt_tokens=tokenize_text(request.prompt),
            attachments=attachments,
            attachment_media=attachment_media,
        )

    def _to_attachment_profile(self, item: dict[str, Any]) -> AttachmentProfile:
        provenance = item.get("provenance")
        supports_multimodal = False
        if isinstance(provenance, dict):
            supports_multimodal = bool(provenance.get("supportsMultimodal"))
        return AttachmentProfile(
            attachment_id=str(item.get("attachmentId") or "").strip(),
            filename=str(item.get("filename") or "").strip(),
            mime_type=str(item.get("mimeType") or "").strip(),
            byte_size=int(item.get("byteSize") or 0),
            document_type=str(item.get("documentType") or "unknown").strip() or "unknown",
            summary=str(item.get("factSummary") or item.get("summary") or "").strip(),
            extracted_text=str(item.get("extractedText") or "").strip(),
            fact_hints=tuple(self._string_list(item.get("extractedFactHints") or item.get("factHints"))),
            structured_facts=self._dict_value(item.get("structuredFacts")),
            warnings=tuple(self._string_list(item.get("factExtractionWarnings") or item.get("warnings"))),
            supports_multimodal=supports_multimodal,
        )

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _dict_value(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        return {str(key): item for key, item in value.items() if str(key).strip()}

    def _select_candidates(
        self,
        request: NormalizedRequest,
        *,
        notes: list[str],
    ) -> tuple[object, ...]:
        try:
            candidates = self.selector.select(request)
            if candidates:
                notes.append("family_selector_used")
                return candidates
            notes.append("family_selector_empty")
        except RawExecutionError:
            notes.append("family_selector_failed")
        fallback_candidates = self.classifier.classify(request)
        if fallback_candidates:
            notes.append("heuristic_classifier_fallback")
        return fallback_candidates

    def _should_fallback_on_confidence(self, analysis: BenchmarkAnalysis, extraction_confidence: float) -> bool:
        if not analysis.candidates:
            return True
        selector_confidence = analysis.candidates[0].confidence
        return selector_confidence < 0.2 and extraction_confidence < 0.2
