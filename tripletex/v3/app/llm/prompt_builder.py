from __future__ import annotations

from typing import Any

from app.contracts import IntentDocument
from app.llm.response_schemas import (
    bridge_fallback_response_json_schema,
    bridge_response_json_schema,
)
from app.llm.spec_reference import SpecReferenceBuilder


class PromptBuilder:
    def __init__(self, spec_reference_builder: SpecReferenceBuilder | None = None) -> None:
        self.spec_reference_builder = spec_reference_builder or SpecReferenceBuilder()

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
        intent: IntentDocument | None,
        context_slice: dict[str, Any],
        replan_feedback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        reference_documents = self.spec_reference_builder.build(context_slice=context_slice)
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
                "The API contract in context.apiContract is authoritative for this prompt: only the listed candidate flow names, command names, and inputs are legal. "
                "The raw API contract in context.rawApiContract is authoritative for this prompt's exact raw operationIds. "
                "The extracted raw OpenAPI slices in referenceDocuments come directly from the authoritative docs/openapi.json. "
                "For business flows and friendly commands, context.apiContract plus selectorFamilies and payloadFamilies are authoritative, even when the underlying raw OpenAPI uses different field names. "
                "For business flows and friendly commands, nested payload objects must use wrapper field names like account_ref, supplier_ref, payment_date, and payment_type_ref. "
                "Use raw OpenAPI field names like account, supplier, paymentDate, or paymentTypeId only inside fallbackRawCommands or explicit raw body/payload passthrough. "
                "When you emit raw fallback inputs or explicit raw request bodies, they must MATCH the extracted OpenAPI slice exactly. "
                "If a field name, nesting shape, enum value, or request body property does not exist in the relevant authoritative contract, do not emit it. "
                "request.intent is a structured routing-intent document extracted in a prior pass from the same prompt and attachments. Use it as routing evidence, "
                "but final legality still comes from context.apiContract, context.rawApiContract, selectorFamilies, payloadFamilies, and referenceDocuments. "
                "request.attachmentFacts and request.attachments[].structuredFacts are pre-normalized attachment JSON extracted before planning; prefer those facts over re-inferring from raw attachment text when they are present. "
                "The selector schemas in context.selectorFamilies are authoritative for selector objects. "
                "The composite payload schemas in context.payloadFamilies are authoritative for object and row payloads. "
                "If a legal flow or command input expects a selector family or a payload *_ref field, you may emit a legal selector object instead of a resolved numeric id. "
                "The raw and command input type hints in context.rawOperations[].inputTypes and context.apiContract.candidateCommands[].inputTypeHints are authoritative for JSON value types. "
                "Do not emit a flowName or commandName outside that contract. "
                "Do not emit flow inputs or command inputs outside that contract. "
                "If a flow or command input is marked with inputSemantics.kind selector, selector_or_create_payload, payload, or array_payload, obey that structure exactly. "
                "For payload-style commands, only wrapperInputs, bodyFields, and the pseudo-inputs body or payload from the contract are legal. "
                "If required inputs are missing, do not guess them; either choose another legal route or set validation.isExecutable=false with blocking issues. "
                "Do not invent near-match aliases. For example, if the contract does not list timesheet.entry.sum then timesheet.entry.sum is illegal. "
                "Emit integers as JSON numbers, booleans as JSON booleans, and object refs as objects with integer id fields. "
                "If a raw or bound input is marked defaultToTokenOwner, omit that input when the task refers to the authenticated employee instead of emitting token_owner or current_user. "
                "If you need a raw fallback, use an exact operationId from context.rawOperations and its exact raw parameter names. "
                "Never emit a raw operationId that is not listed in context.rawApiContract.candidateOperationIds. "
                "For raw fallbacks, only context.rawOperations[].allowedInputs are legal input names. "
                "If a raw fallback has requestBodyKind multipart or json, use only its listed bodyFields or a body object with those exact fields. "
                "If a task needs mutation fields that are not listed in a raw operation bodyFields, that raw operation is not a legal route for the task. "
                "Do not invent alternative raw body field names such as employee versus employeeId; either choose a documented flow/command or block execution. "
                "Exact raw operationIds must be emitted only in executionPlan.fallbackRawCommands, never in executionPlan.selectedCommands. "
                "executionPlan.selectedCommands is only for legal friendly command names from context.apiContract.candidateCommands. "
                "Routing priority is strict: choose a documented business flow first, then a documented friendly command, then exact raw operationId fallback. "
                "If a documented business flow exists for a mutation, do not choose the direct mutation command instead. "
                "If a selected business flow already accepts an array payload such as postings, costs, or lines, prefer one flow step with multiple rows over duplicating the same flow multiple times. "
                "Do not add diagnostic read-only raw steps just to compensate for missing mutation ids when the selected business flow can resolve legal selector objects internally. "
                "Do not reference prior step outputs inside ids or ref objects such as step_1.project.id; the runtime does not dereference step-output placeholders. "
                "When later work depends on earlier created objects, reuse selectors from the prompt or attachment facts, or choose a business flow that resolves the dependency internally. "
                "If a selected flow, command, or raw operation has a conformance policy key, obey the matching summary in context.policyCatalog. "
                "Every selected step needs a stable stepId. "
                "Do not omit stepId on any flow, command, or raw step. "
                "All step-specific legal inputs must appear in step.inputs or in flatBridge.flowArguments / flatBridge.commandArguments for that exact legal flow or command. "
                "flatBridge.fieldBag is only for duplicated aliases and denormalized facts, not for hiding required step inputs. "
                "For employee selectors, a human full name is not a legal field by itself; split it into first_name and last_name or use email. "
                "validation.blockingIssues, validation.warnings, and validation.missingRequiredData must be arrays of plain strings, not objects. "
                "A blocked plan with zero selected routes is only valid when the listed candidate routes still cannot be used because concrete facts or selectors are missing; "
                "do not claim the tooling is unavailable when matching candidates exist in the context contract. "
                f"{attachment_rule}"
                "If execution is blocked, set validation.isExecutable=false and explain the blocking issues inside the JSON instead of writing prose."
            ),
            "request": {
                "prompt": prompt,
                "currentDate": current_date,
                "timezone": timezone,
                "intent": intent.model_dump(mode="json") if intent is not None else None,
                "replanFeedback": replan_feedback,
                "attachments": evidence,
                "attachmentFacts": self._attachment_fact_summary(evidence),
            },
            "referenceDocuments": reference_documents,
            "responseJsonSchema": bridge_response_json_schema(),
            "fallbackResponseJsonSchema": bridge_fallback_response_json_schema(),
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
                    "treat context.apiContract as the hard candidate allow-list for legal flow names, legal command names, and legal inputs",
                    "before emitting each selected flow or selected command, verify its name exists exactly in the API contract",
                    "before emitting each selected flow or selected command, verify every emitted input name exists exactly in that contract entry",
                    "before marking the plan executable, verify all required inputs for every selected flow or selected command are present",
                    "prefer request.attachmentFacts and request.attachments[].structuredFacts as the authoritative normalized attachment facts when present",
                    "before emitting a selector object, verify its nested keys are legal for that selector family in context.selectorFamilies",
                    "before emitting a composite object or row array, verify its nested keys satisfy the matching payload family in context.payloadFamilies",
                    "for selector-capable *_ref fields inside payload families, emit a legal selector object when the prompt gives identifying details but not a numeric id",
                    "duplicate useful aliases into flatBridge.fieldBag and byEntityId",
                    "bind friendly flow inputs by friendly names",
                    "use apiContract.candidateCommands and apiContract.candidateFlows for the complete detailed contract surface",
                    "use apiContract.candidateCommands to verify every command name and required input before emitting a selected command",
                    "use apiContract.candidateFlows to verify every flow name and required input before emitting a selected flow",
                    "if a mutation command has a documented business flow, prefer the business flow over the direct command",
                    "bind raw fallback inputs only by exact input names from context.rawOperations[].allowedInputs",
                    "if a raw mutation needs body fields outside context.rawOperations[].bodyFields, do not use that raw operation",
                    "use context.rawOperations[].inputTypes and context.apiContract.candidateCommands[].inputTypeHints to emit the correct JSON type for every argument",
                    "when an input is marked defaultToTokenOwner, omit it instead of emitting token_owner/current_user",
                    "never use step-output placeholder strings such as step_1.project.id inside selector refs, body refs, or raw ids because the runtime does not dereference them",
                    "for business flows and friendly commands, use wrapper input names and payload family field names even if the raw OpenAPI uses different names",
                    "for raw_operation steps or explicit raw body/payload passthrough, use the extracted raw OpenAPI field names exactly as shown in referenceDocuments",
                    "if request.attachments is empty, do not select attachment_accounting routes or any step that requires attachment_id",
                    "if one flow already accepts an array payload that can express all requested rows or postings, emit one flow step with that array instead of duplicating the same flow name",
                    "avoid diagnostic read-only raw steps unless the prompt explicitly asks for them or the contract requires them",
                    "emit validation.blockingIssues and validation.warnings as plain string arrays",
                    "place raw operationIds only in executionPlan.fallbackRawCommands with commandType raw_operation and operationId set",
                    "never place a raw operationId in executionPlan.selectedCommands",
                    "include stepOrder whenever multiple steps exist",
                    "prefer minimal correct execution plans",
                ],
                "invalidPatterns": [
                    {
                        "bad": {"commandName": "timesheet.entry.sum"},
                        "why": "Not listed in apiContract.candidateCommands.",
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
                        "why": "Only exact legal command names from apiContract.candidateCommands are allowed.",
                    },
                    {
                        "bad": {"commandName": "employee.create"},
                        "why": "If a documented business flow exists for the mutation, use the flow instead of the direct mutation command.",
                    },
                    {
                        "bad": {"commandName": "employee.search", "inputs": {"name": "Jane Doe"}},
                        "why": "employee selectors use first_name and last_name or email, not name.",
                    },
                    {
                        "bad": {"commandName": "voucher.create", "inputs": {"postings": [{"project_ref": "step_1.project.id"}]}},
                        "why": "The runtime does not dereference step-output placeholders inside refs or body ids.",
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
