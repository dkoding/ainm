from __future__ import annotations

import json
from typing import Any

from app.llm.gemini_client import GeminiClient
from app.llm.response_schemas import (
    bridge_fallback_response_json_schema,
    bridge_response_json_schema,
)


class RepairEngine:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()

    def repair(self, invalid_payload: str, errors: list[str], *, prompt_package: dict[str, Any] | None = None) -> str:
        request_payload: dict[str, Any] = {"invalidJson": invalid_payload, "errors": errors}
        if prompt_package is not None:
            request_payload["originalRequest"] = prompt_package.get("request", {})
            request_payload["originalContext"] = prompt_package.get("context", {})
            request_payload["originalReferenceDocuments"] = prompt_package.get("referenceDocuments", [])
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
                "Do not invent near-match field names or undocumented raw body fields. "
                "Do not introduce direct mutation commands when a documented business flow exists for the same task. "
                "Do not emit step-output placeholder ids such as step_1.project.id; the runtime does not dereference them. "
                "If a raw mutation cannot be expressed using the documented contract, reroute to a documented flow/command or set validation.isExecutable=false. "
                "If the API error reports a missing required field or empty mandatory value that cannot be filled from the existing prompt, attachment facts, or bridge data, "
                "set validation.isExecutable=false with blocking issues instead of retrying the same mutation shape. "
                "If originalRequest.attachments is empty, do not keep or introduce attachment_accounting routes or attachment_id inputs. "
                "validation.blockingIssues and validation.warnings must stay arrays of plain strings, not objects. "
                "If the task cannot be completed legally from the available facts, set validation.isExecutable=false "
                "and explain the blocking issue inside the JSON."
                ),
                "request": {
                    "originalBridge": json.dumps(bridge, ensure_ascii=False),
                    "lastError": error,
                    "originalRequest": prompt_package.get("request", {}),
                },
                "context": prompt_package.get("context", {}),
                "referenceDocuments": prompt_package.get("referenceDocuments", []),
                "responseJsonSchema": bridge_response_json_schema(),
                "fallbackResponseJsonSchema": bridge_fallback_response_json_schema(),
            }
        )
