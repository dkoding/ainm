from __future__ import annotations

import re
import unicodedata

from app.benchmark.models import FamilyCandidate, NormalizedRequest
from app.benchmark.registry import TaskRegistry


TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    lowered = ascii_text.lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(cleaned.split())


def tokenize_text(value: str) -> tuple[str, ...]:
    normalized = normalize_text(value)
    if not normalized:
        return ()
    return tuple(TOKEN_RE.findall(normalized))


class FamilyClassifier:
    def __init__(self, registry: TaskRegistry | None = None) -> None:
        self.registry = registry or TaskRegistry()

    def classify(self, request: NormalizedRequest, *, limit: int = 5) -> tuple[FamilyCandidate, ...]:
        prompt_text = request.prompt_normalized
        candidates: list[FamilyCandidate] = []
        for manifest in self.registry.all():
            score = 0.0
            reasons: list[str] = []
            if manifest.requires_attachment and request.has_attachments:
                score += 2.0
                reasons.append("attachment_present")
            if manifest.attachment_document_types and request.attachment_document_types:
                normalized_types = {normalize_text(item) for item in request.attachment_document_types}
                if any(normalize_text(item) in normalized_types for item in manifest.attachment_document_types):
                    score += 3.0
                    reasons.append("attachment_document_type_match")
            family_tokens = set(tokenize_text(manifest.family_id.replace(".", " ")))
            summary_tokens = set(tokenize_text(manifest.summary))
            overlap = family_tokens.intersection(set(request.prompt_tokens)) | summary_tokens.intersection(set(request.prompt_tokens))
            if overlap:
                score += 0.5 + len(overlap) * 0.2
                reasons.append("canonical_overlap")
            if score <= 0:
                continue
            confidence = max(0.05, min(score / 10.0, 0.6))
            candidates.append(
                FamilyCandidate(
                    family_id=manifest.family_id,
                    score=round(score, 3),
                    confidence=round(confidence, 3),
                    matched_terms=(),
                    matched_slots=(),
                    reasons=tuple(reasons),
                )
            )
        candidates.sort(key=lambda candidate: (-candidate.score, candidate.family_id))
        return tuple(candidates[:limit])
