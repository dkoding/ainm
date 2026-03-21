from __future__ import annotations

import base64
import json
from typing import Any

from app.contracts.solve import SolveFile


class AttachmentEvidenceBuilder:
    def build(self, files: list[SolveFile]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for index, file in enumerate(files, start=1):
            decoded_text = self._extract_text(file)
            evidence.append(
                {
                    "attachmentId": f"attachment_{index}",
                    "filename": file.filename,
                    "mimeType": file.mime_type,
                    "textOriginal": decoded_text,
                    "textCanonical": decoded_text,
                    "ocrConfidence": 1.0 if decoded_text else 0.0,
                    "tables": [],
                    "detectedLanguages": [],
                    "extractedFactHints": [],
                }
            )
        return evidence

    def _extract_text(self, file: SolveFile) -> str:
        try:
            payload = base64.b64decode(file.content_base64)
        except Exception:
            return ""
        if file.mime_type.startswith("text/") or file.filename.endswith((".txt", ".csv", ".json", ".md")):
            try:
                if file.filename.endswith(".json"):
                    parsed = json.loads(payload.decode("utf-8"))
                    return json.dumps(parsed, ensure_ascii=False)
                return payload.decode("utf-8")
            except Exception:
                return payload.decode("utf-8", errors="ignore")
        return ""
