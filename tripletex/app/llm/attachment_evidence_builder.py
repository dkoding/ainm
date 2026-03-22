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
            evidence.append(
                {
                    "attachmentId": f"attachment_{index}",
                    "filename": file.filename,
                    "mimeType": file.mime_type,
                    "byteSize": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest() if payload else "",
                    "textOriginal": decoded_text,
                    "textCanonical": decoded_text,
                    "ocrConfidence": 1.0 if decoded_text else 0.0,
                    "tables": [],
                    "detectedLanguages": [],
                    "extractedFactHints": [],
                    "provenance": {
                        "source": "local_extract",
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
