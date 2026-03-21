from __future__ import annotations

from app.llm.gemini_client import GeminiClient


class RepairEngine:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()

    def repair(self, invalid_payload: str, errors: list[str]) -> str:
        return self.client.repair(invalid_payload, errors)
