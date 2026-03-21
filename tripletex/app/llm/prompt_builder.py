from __future__ import annotations

from typing import Any


class PromptBuilder:
    def build(
        self,
        *,
        prompt: str,
        evidence: list[dict[str, Any]],
        current_date: str,
        timezone: str,
        context_slice: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "systemInstruction": (
                "You are the Tripletex bridge planner. "
                "Return exactly one JSON object and no prose. "
                "The JSON must use contractVersion tripletex.llm_bridge.v1 and include all top-level sections: "
                "requestContext, language, understanding, sources, richData, flatBridge, executionPlan, validation, completion. "
                "Use English field names, preserve source text, and normalize dates to ISO form. "
                "Never invent IDs, missing facts, or unsupported commands. "
                "Routing priority is strict: choose a documented business flow first, then a documented friendly command, then exact raw operationId fallback. "
                "Every selected step needs a stable stepId. "
                "If execution is blocked, set validation.isExecutable=false and explain the blocking issues inside the JSON instead of writing prose."
            ),
            "request": {
                "prompt": prompt,
                "currentDate": current_date,
                "timezone": timezone,
                "attachments": evidence,
            },
            "context": {
                **context_slice,
                "contractSkeleton": {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "requestContext": {},
                    "language": {},
                    "understanding": {},
                    "sources": {},
                    "richData": {},
                    "flatBridge": {},
                    "executionPlan": {
                        "selectedFlows": [],
                        "selectedCommands": [],
                        "fallbackRawCommands": [],
                        "stepOrder": [],
                    },
                    "validation": {},
                    "completion": {},
                },
                "requiredBehaviors": [
                    "duplicate useful aliases into flatBridge.fieldBag and byEntityId",
                    "bind friendly flow inputs by friendly names",
                    "bind raw fallback inputs by exact raw parameter names",
                    "include stepOrder whenever multiple steps exist",
                    "prefer minimal correct execution plans",
                ],
                "examples": [
                    {
                        "kind": "business_flow",
                        "prompt": "Create a customer named Jason Bourne with email jason@example.org",
                        "flowName": "customer.create_or_update",
                        "commandNames": ["customer.search", "customer.create"],
                    },
                    {
                        "kind": "raw_fallback",
                        "prompt": "How many hours did I work in February?",
                        "technicalFlowFamily": "timesheet.entry.read",
                        "operationId": "TimesheetEntryTotalHours_getTotalHours",
                    },
                ],
            },
        }
