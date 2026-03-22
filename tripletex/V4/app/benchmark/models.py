from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SlotDefinition:
    name: str
    description: str
    required: bool = True
    data_type: str = "string"
    attachment_derived: bool = False


@dataclass(frozen=True, slots=True)
class TaskFamilyManifest:
    family_id: str
    category: str
    summary: str
    executor_name: str
    preferred_flow_name: str | None = None
    preferred_command_names: tuple[str, ...] = ()
    preferred_raw_operation_id: str | None = None
    requires_attachment: bool = False
    attachment_document_types: tuple[str, ...] = ()
    required_slots: tuple[SlotDefinition, ...] = ()
    optional_slots: tuple[SlotDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class AttachmentProfile:
    attachment_id: str
    filename: str
    mime_type: str
    byte_size: int
    document_type: str
    summary: str
    extracted_text: str
    fact_hints: tuple[str, ...] = ()
    structured_facts: dict[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    supports_multimodal: bool = False


@dataclass(frozen=True, slots=True)
class NormalizedRequest:
    prompt: str
    prompt_normalized: str
    prompt_tokens: tuple[str, ...]
    attachments: tuple[AttachmentProfile, ...] = ()
    attachment_media: tuple[dict[str, object], ...] = ()

    @property
    def has_attachments(self) -> bool:
        return bool(self.attachments)

    @property
    def attachment_document_types(self) -> tuple[str, ...]:
        document_types = [
            item.document_type.strip().lower()
            for item in self.attachments
            if item.document_type.strip()
        ]
        return tuple(document_types)


@dataclass(frozen=True, slots=True)
class FamilyCandidate:
    family_id: str
    score: float
    confidence: float
    matched_terms: tuple[str, ...]
    matched_slots: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkAnalysis:
    normalized_request: NormalizedRequest
    selected_family_id: str | None
    selected_route_kind: str | None
    selected_route_name: str | None
    selected_flow_name: str | None
    selected_executor_name: str | None
    supported_by_executor: bool
    execution_mode: str
    candidates: tuple[FamilyCandidate, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkRouteContract:
    route_kind: str
    route_name: str
    legal_inputs: tuple[str, ...]
    required_input_groups: tuple[tuple[str, ...], ...] = ()
    input_semantics: dict[str, dict[str, object]] = field(default_factory=dict)
    selector_families: dict[str, dict[str, object]] = field(default_factory=dict)
    payload_families: dict[str, dict[str, object]] = field(default_factory=dict)
    create_payload_contracts: dict[str, dict[str, object]] = field(default_factory=dict)
    openapi_hints: dict[str, dict[str, object]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FamilyExtraction:
    family_id: str
    route_kind: str
    route_name: str
    inputs: dict[str, object] = field(default_factory=dict)
    missing_required_inputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    confidence: float = 0.0
