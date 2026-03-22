from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from typing import Any

from app.contracts.solve import SolveFile


class AttachmentEvidenceBuilder:
    def build(self, files: list[SolveFile]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for index, file in enumerate(files, start=1):
            payload = self._decode(file)
            decoded_text = self._extract_text(file, payload)
            extraction_mode = self._extraction_mode(file, payload, decoded_text)
            warnings = self._warnings(file, payload, decoded_text, extraction_mode)
            extraction_confidence = self._extraction_confidence(decoded_text)
            evidence.append(
                {
                    "attachmentId": f"attachment_{index}",
                    "filename": file.filename,
                    "mimeType": file.mime_type,
                    "byteSize": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest() if payload else "",
                    "extractedText": decoded_text,
                    "textOriginal": decoded_text,
                    "textCanonical": decoded_text,
                    "ocrText": "",
                    "extractionConfidence": extraction_confidence,
                    "ocrConfidence": 0.0,
                    "tables": [],
                    "warnings": warnings,
                    "detectedLanguages": [],
                    "extractedFactHints": [],
                    "provenance": {
                        "source": "local_extract",
                        "mode": extraction_mode,
                        "supportsMultimodal": self._supports_multimodal(file.mime_type),
                    },
                }
            )
        return evidence

    def _decode(self, file: SolveFile) -> bytes:
        try:
            return base64.b64decode(file.content_base64)
        except Exception:
            return b""

    def _extract_text(self, file: SolveFile, payload: bytes) -> str:
        if not payload:
            return ""
        if file.mime_type.startswith("text/") or file.filename.endswith((".txt", ".csv", ".json", ".md")):
            try:
                if file.filename.endswith(".json"):
                    parsed = json.loads(payload.decode("utf-8"))
                    return json.dumps(parsed, ensure_ascii=False)
                return payload.decode("utf-8")
            except Exception:
                return payload.decode("utf-8", errors="ignore")
        if file.mime_type == "application/pdf" or file.filename.lower().endswith(".pdf"):
            return self._extract_pdf_text(payload)
        return ""

    def _extraction_mode(self, file: SolveFile, payload: bytes, decoded_text: str) -> str:
        if not payload:
            return "decode_failed"
        if file.mime_type.startswith("text/") or file.filename.endswith((".txt", ".csv", ".json", ".md")):
            return "local_text_extract"
        if file.mime_type == "application/pdf" or file.filename.lower().endswith(".pdf"):
            return "local_pdf_extract" if decoded_text else "multimodal_only"
        if self._supports_multimodal(file.mime_type):
            return "multimodal_only"
        return "unsupported_binary"

    def _warnings(self, file: SolveFile, payload: bytes, decoded_text: str, extraction_mode: str) -> list[str]:
        if not payload:
            return ["Attachment content could not be decoded from base64."]
        if decoded_text:
            return []
        if extraction_mode == "multimodal_only":
            if file.mime_type == "application/pdf" or file.filename.lower().endswith(".pdf"):
                return ["No embedded PDF text was extracted locally; rely on Gemini multimodal analysis for document understanding."]
            return ["No local text extraction is available for this attachment; rely on Gemini multimodal analysis."]
        if extraction_mode == "unsupported_binary":
            return ["No local text extraction is available for this binary attachment."]
        return []

    def _extraction_confidence(self, decoded_text: str) -> float:
        return 1.0 if decoded_text else 0.0

    def _extract_pdf_text(self, payload: bytes) -> str:
        try:
            from pypdf import PdfReader
        except Exception:
            return ""
        try:
            reader = PdfReader(BytesIO(payload))
        except Exception:
            return ""
        pages: list[str] = []
        for page in reader.pages[:20]:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            if text.strip():
                pages.append(text.strip())
        return "\n\n".join(pages)

    def _supports_multimodal(self, mime_type: str) -> bool:
        return mime_type.startswith("image/") or mime_type == "application/pdf"
