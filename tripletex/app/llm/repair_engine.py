from __future__ import annotations

import json
from typing import Any

from app.llm.gemini_client import GeminiClient


class RepairEngine:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()

    def repair(self, invalid_payload: str, errors: list[str], *, prompt_package: dict[str, Any] | None = None) -> str:
        request_payload: dict[str, Any] = {"invalidJson": invalid_payload, "errors": errors}
        if prompt_package is not None:
            request_payload["originalRequest"] = prompt_package.get("request", {})
            request_payload["originalContext"] = prompt_package.get("context", {})
        return self.client.repair(request_payload)

    def repair_after_execution_error(
        self,
        *,
        bridge: dict[str, Any],
        error: dict[str, Any],
        prompt_package: dict[str, Any],
    ) -> str:
        return self.client.generate(
            {
                "systemInstruction": (
                    "Repair the provided Tripletex bridge JSON after a concrete execution or validation error. "
                    "Return exactly one valid bridge JSON object and no prose. "
                    "Make the minimal legal changes needed to avoid the reported failure. "
                    "If the task cannot be completed legally from the available facts, set validation.isExecutable=false "
                    "and explain the blocking issue inside the JSON."
                ),
                "request": {
                    "originalBridge": json.dumps(bridge, ensure_ascii=False),
                    "lastError": error,
                    "originalRequest": prompt_package.get("request", {}),
                },
                "context": prompt_package.get("context", {}),
            }
        )
