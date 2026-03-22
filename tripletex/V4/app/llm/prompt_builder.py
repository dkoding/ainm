from __future__ import annotations

from typing import Any


class PromptBuilder:
    def _attachment_fact_summary(self, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for attachment in evidence:
            facts.append(
                {
                    "attachmentId": attachment.get("attachmentId"),
                    "documentType": attachment.get("documentType"),
                    "summary": attachment.get("factSummary", ""),
                    "factHints": attachment.get("extractedFactHints", []),
                    "structuredFacts": attachment.get("structuredFacts", {}),
                    "warnings": attachment.get("factExtractionWarnings", []),
                    "confidence": attachment.get("factExtractionConfidence"),
                }
            )
        return facts

    def build(
        self,
        *,
        prompt: str,
        evidence: list[dict[str, Any]],
        attachment_media: list[dict[str, Any]],
        current_date: str,
        timezone: str,
        context_slice: dict[str, Any],
    ) -> dict[str, Any]:
        attachment_rule = (
            "The request has no attachments. Any flow, command, or raw operation that requires attachment_accounting or attachment_id is illegal; "
            "set validation.isExecutable=false with a blocking issue instead of selecting it. "
            if not evidence
            else "Only attachment IDs listed in request.attachments are legal attachment_id values. "
        )
        return {
            "systemInstruction": (
                "You are the Tripletex bridge planner. "
                "Return exactly one JSON object and no prose. "
                "The JSON must use contractVersion tripletex.llm_bridge.v1 and include all top-level sections: "
                "requestContext, language, understanding, sources, richData, flatBridge, executionPlan, validation, completion. "
                "Use English field names, preserve source text, and normalize dates to ISO form. "
                "Never invent IDs, missing facts, or unsupported commands. "
                "The API contract in context.apiContract is authoritative: only those flow names, command names, and inputs are legal. "
                "The raw API contract in context.rawApiContract is authoritative for exact raw operationIds. "
                "request.attachmentFacts and request.attachments[].structuredFacts are pre-normalized attachment JSON extracted before planning; prefer those facts over re-inferring from raw attachment text when they are present. "
                "sources.prompt must be a plain string with the original prompt text, not an object. "
                "The selector schemas in context.selectorFamilies are authoritative for selector objects. "
                "The composite payload schemas in context.payloadFamilies are authoritative for object and row payloads. "
                "The raw and command input type hints in context.rawOperations[].inputTypes and context.apiContract.legalCommands[].inputTypeHints are authoritative for JSON value types. "
                "context.apiContract.legalCommands[].availability and context.rawOperations[].availability are authoritative for restricted or pilot-only APIs. "
                "Do not emit a flowName or commandName outside that contract. "
                "Do not emit flow inputs or command inputs outside that contract. "
                "If a flow or command input is marked with inputSemantics.kind selector, selector_or_create_payload, payload, or array_payload, obey that structure exactly. "
                "For payload-style commands, only wrapperInputs, bodyFields, and the pseudo-inputs body or payload from the contract are legal. "
                "If required inputs are missing, do not guess them; either choose another legal route or set validation.isExecutable=false with blocking issues. "
                "Do not invent near-match aliases. For example, if the contract does not list timesheet.entry.sum then timesheet.entry.sum is illegal. "
                "Emit integers as JSON numbers, booleans as JSON booleans, and object refs as objects with integer id fields. "
                "If a raw or bound input is marked defaultToTokenOwner, omit that input when the task refers to the authenticated employee instead of emitting token_owner or current_user. "
                "If you need a raw fallback, use an exact operationId from context.rawOperations and its exact raw parameter names. "
                "Never emit a raw operationId that is not listed in context.rawApiContract.legalOperationIds. "
                "For raw fallbacks, only context.rawOperations[].allowedInputs are legal input names. "
                "If a raw fallback has requestBodyKind multipart or json, use only its listed bodyFields or a body object with those exact fields. "
                "If a task needs mutation fields that are not listed in a raw operation bodyFields, that raw operation is not a legal route for the task. "
                "Do not invent alternative raw body field names such as employee versus employeeId; either choose a documented flow/command or block execution. "
                "Exact raw operationIds must be emitted only in executionPlan.fallbackRawCommands, never in executionPlan.selectedCommands. "
                "executionPlan.selectedCommands is only for legal friendly command names from context.apiContract.legalCommands. "
                "Routing priority is strict: choose a documented business flow first, then a documented friendly command, then exact raw operationId fallback. "
                "If a documented business flow exists for a mutation, do not choose the direct mutation command instead. "
                "Do not use bare placeholder strings such as step_1.project.id. "
                "When a later step needs an exact value from an earlier result, use a step-output binding object of the form "
                "{\"$fromStep\":\"step_1\",\"path\":\"value.id\"}. "
                "The path may include dotted object keys and numeric list indexes like values[0].id. "
                "Use restricted or pilot-only APIs only when the requested final state actually requires them; never use them for optional readback or optional verification. "
                "If a selected flow, command, or raw operation has a conformance policy key, obey the matching summary in context.policyCatalog. "
                "Every selected step needs a stable stepId. "
                "Do not omit stepId on any flow, command, or raw step. "
                "All step-specific legal inputs must appear in step.inputs or in flatBridge.flowArguments / flatBridge.commandArguments for that exact legal flow or command. "
                "flatBridge.fieldBag is only for duplicated aliases and denormalized facts, not for hiding required step inputs. "
                "For employee selectors, a human full name is not a legal field by itself; split it into first_name and last_name or use email. "
                "validation.blockingIssues, validation.warnings, and validation.missingRequiredData must be arrays of plain strings, not objects. "
                f"{attachment_rule}"
                "If execution is blocked, set validation.isExecutable=false and explain the blocking issues inside the JSON instead of writing prose."
            ),
            "request": {
                "prompt": prompt,
                "currentDate": current_date,
                "timezone": timezone,
                "attachments": evidence,
                "attachmentFacts": self._attachment_fact_summary(evidence),
            },
            "media": attachment_media,
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
                    "prefer request.attachmentFacts and request.attachments[].structuredFacts as the authoritative normalized attachment facts when present",
                    "before emitting a selector object, verify its nested keys are legal for that selector family in context.selectorFamilies",
                    "before emitting a composite object or row array, verify its nested keys satisfy the matching payload family in context.payloadFamilies",
                    "duplicate useful aliases into flatBridge.fieldBag and byEntityId",
                    "bind friendly flow inputs by friendly names",
                    "use context.commands and context.flows for the complete detailed contract surface",
                    "use apiContract.legalCommands to verify every command name and required input before emitting a selected command",
                    "use apiContract.legalFlows to verify every flow name and required input before emitting a selected flow",
                    "if a mutation command has a documented business flow, prefer the business flow over the direct command",
                    "bind raw fallback inputs only by exact input names from context.rawOperations[].allowedInputs",
                    "if a raw mutation needs body fields outside context.rawOperations[].bodyFields, do not use that raw operation",
                    "use context.rawOperations[].inputTypes and context.apiContract.legalCommands[].inputTypeHints to emit the correct JSON type for every argument",
                    "preserve the original prompt as a plain string in sources.prompt",
                    "when a later step needs a concrete value from an earlier step, use a step-output binding object with $fromStep and path instead of a placeholder string",
                    "avoid restricted or pilot-only APIs for optional follow-up reads or optional verification",
                    "when an input is marked defaultToTokenOwner, omit it instead of emitting token_owner/current_user",
                    "never use step-output placeholder strings such as step_1.project.id inside selector refs, body refs, or raw ids",
                    "if request.attachments is empty, do not select attachment_accounting routes or any step that requires attachment_id",
                    "emit validation.blockingIssues and validation.warnings as plain string arrays",
                    "place raw operationIds only in executionPlan.fallbackRawCommands with commandType raw_operation and operationId set",
                    "never place a raw operationId in executionPlan.selectedCommands",
                    "include stepOrder whenever multiple steps exist",
                    "prefer minimal correct execution plans",
                ],
                "invalidPatterns": [
                    {
                        "bad": {"commandName": "timesheet.entry.sum"},
                        "why": "Not listed in apiContract.legalCommands.",
                    },
                    {
                        "bad": {
                            "selectedCommands": [
                                {
                                    "commandName": "TimesheetEntryTotalHours_getTotalHours",
                                    "commandType": "friendly_alias",
                                }
                            ]
                        },
                        "why": "Raw operationIds must go in fallbackRawCommands, not selectedCommands.",
                    },
                    {
                        "bad": {
                            "operationId": "LedgerVoucherImportDocument_importDocument",
                            "inputs": {"attachmentId": "attachment_1", "task": "bookkeep this"},
                        },
                        "why": "Those keys are not listed in context.rawOperations[].allowedInputs for that raw operation.",
                    },
                    {
                        "bad": {
                            "operationId": "SalaryTransaction_post",
                            "inputs": {
                                "body": {"amount": 50000, "date": "2026-03-31", "employeeId": 7, "salaryTypeId": 3}
                            },
                        },
                        "why": "Raw body fields must exist exactly in the operation bodyFields. If the body schema does not expose those fields, do not use the raw operation.",
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
                    {
                        "bad": {"commandName": "supplier.search"},
                        "why": "Only exact legal command names from apiContract.legalCommands are allowed.",
                    },
                    {
                        "bad": {"commandName": "employee.create"},
                        "why": "If a documented business flow exists for the mutation, use the flow instead of the direct mutation command.",
                    },
                    {
                        "bad": {"sources": {"prompt": {"text": "Create customer", "normalizedDate": "2026-03-22"}}},
                        "why": "sources.prompt must be a plain string, not an object.",
                    },
                    {
                        "bad": {"commandName": "employee.search", "inputs": {"name": "Jane Doe"}},
                        "why": "employee selectors use first_name and last_name or email, not name.",
                    },
                    {
                        "bad": {"commandName": "voucher.create", "inputs": {"postings": [{"project_ref": "step_1.project.id"}]}},
                        "why": "Use a step-output binding object instead of a placeholder string.",
                    },
                    {
                        "bad": {"commandName": "incoming_invoice.get", "why": "optional readback after import"},
                        "why": "Restricted or pilot-only APIs must not be used for optional follow-up reads when the task is already complete.",
                    },
                    {
                        "bad": {"commandName": "voucher.create", "inputs": {"voucher_type_ref": "Inngående faktura"}},
                        "why": "ref inputs must be resolved ids or id objects, not human labels.",
                    },
                    {
                        "bad": {"selectedFlows": [{"flowName": "project.create_for_customer"}]},
                        "why": "Every selected step must include stepId.",
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
                        "kind": "business_flow",
                        "prompt": "Create a project for customer ACME AS with Jane Doe as project manager",
                        "flowName": "project.create_for_customer",
                        "flowInputs": {
                            "customer": {"name": "ACME AS"},
                            "project_manager": {"first_name": "Jane", "last_name": "Doe"},
                        },
                    },
                    {
                        "kind": "raw_fallback",
                        "prompt": "How many hours did I work in February?",
                        "technicalFlowFamily": "timesheet.entry.read",
                        "operationId": "TimesheetEntryTotalHours_getTotalHours",
                        "commandArguments": {"startDate": "2026-02-01", "endDate": "2026-03-01"},
                    },
                    {
                        "kind": "business_flow",
                        "prompt": "Create or update supplier ACME AS with organization number 123456789",
                        "flowName": "supplier.create_or_update",
                        "commandNames": ["supplier.search", "supplier.create", "supplier.update"],
                    },
                    {
                        "kind": "attachment_accounting",
                        "prompt": "Bookkeep the attached supplier invoice",
                        "flowName": "supplier_invoice.import_from_attachment",
                        "commandNames": [
                            "ledger.voucher.import_document",
                            "incoming_invoice.get",
                            "incoming_invoice.update",
                            "supplier_invoice.voucher.update_postings",
                        ],
                    },
                    {
                        "kind": "blocked_plan",
                        "prompt": "Register a travel expense for last week",
                        "result": (
                            "If employee or travel_details cannot be formed as legal structured inputs, "
                            "set validation.isExecutable=false instead of selecting travel_expense.create_with_rows."
                        ),
                    },
                    {
                        "kind": "blocked_plan",
                        "prompt": "Pay the supplier invoice from the attachment, but no supplier or payment type can be resolved",
                        "result": "validation.isExecutable=false with blockingIssues that explain the missing supplier or payment setup",
                    },
                ],
            },
        }
