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
                "The API contract in context.apiContract is authoritative: only those flow names, command names, and inputs are legal. "
                "Do not emit a flowName or commandName outside that contract. "
                "Do not emit flow inputs or command inputs outside that contract. "
                "For payload-style commands, only wrapperInputs, bodyFields, and the pseudo-inputs body or payload from the contract are legal. "
                "If required inputs are missing, do not guess them; either choose another legal route or set validation.isExecutable=false with blocking issues. "
                "Do not invent near-match aliases. For example, if the contract does not list timesheet.entry.sum then timesheet.entry.sum is illegal. "
                "If you need a raw fallback, use an exact operationId from context.rawOperations and its exact raw parameter names. "
                "Routing priority is strict: choose a documented business flow first, then a documented friendly command, then exact raw operationId fallback. "
                "Every selected step needs a stable stepId. "
                "All step-specific legal inputs must appear in step.inputs or in flatBridge.flowArguments / flatBridge.commandArguments for that exact legal flow or command. "
                "flatBridge.fieldBag is only for duplicated aliases and denormalized facts, not for hiding required step inputs. "
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
                    "treat context.apiContract as the hard allow-list for legal flow names, legal command names, and legal inputs",
                    "before emitting each selected flow or selected command, verify its name exists exactly in the API contract",
                    "before emitting each selected flow or selected command, verify every emitted input name exists exactly in that contract entry",
                    "before marking the plan executable, verify all required inputs for every selected flow or selected command are present",
                    "duplicate useful aliases into flatBridge.fieldBag and byEntityId",
                    "bind friendly flow inputs by friendly names",
                    "use context.commands and context.flows for the complete detailed contract surface",
                    "use apiContract.legalCommands to verify every command name and required input before emitting a selected command",
                    "use apiContract.legalFlows to verify every flow name and required input before emitting a selected flow",
                    "bind raw fallback inputs by exact raw parameter names",
                    "include stepOrder whenever multiple steps exist",
                    "prefer minimal correct execution plans",
                ],
                "invalidPatterns": [
                    {
                        "bad": {"commandName": "timesheet.entry.sum"},
                        "why": "Not listed in apiContract.legalCommands.",
                    },
                    {
                        "bad": {"commandName": "invoice.create", "inputs": {"customer_id": 7}},
                        "why": "invoice.create allows customer_ref, not customer_id.",
                    },
                    {
                        "bad": {"commandName": "customer.update", "inputs": {"customer_id": 7}},
                        "why": "customer.update may use id plus legal payload fields like name/email or a payload/body dict, but customer_id is not a legal input.",
                    },
                    {
                        "bad": {"flowName": "customer.create_or_update", "inputs": {"customer_id": 7}},
                        "why": "customer.create_or_update does not list customer_id as a legal flow input.",
                    },
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
