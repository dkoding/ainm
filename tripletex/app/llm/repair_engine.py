from __future__ import annotations

from app.contracts import LLMBridgeDocument
from app.llm.gemini_client import GeminiClient
from app.llm.response_validator import ResponseValidator


class RepairEngine:
    def __init__(self, client: GeminiClient | None = None, validator: ResponseValidator | None = None) -> None:
        self.client = client or GeminiClient()
        self.validator = validator or ResponseValidator()

    def repair(self, invalid_payload: str, errors: list[str]) -> LLMBridgeDocument:
        repaired = self.client.repair(invalid_payload, errors)
        return self.validator.validate(repaired)
