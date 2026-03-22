from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path

from app.contracts import IntentDocument
from app.contracts.solve import SolveFile
from app.contracts.solve import SolveRequest
from app.llm import LLMPlanner


class CapturingClient:
    def __init__(self, responses: list[dict[str, object]] | dict[str, object]) -> None:
        if isinstance(responses, dict):
            responses = [responses]
        self.responses = list(responses)
        self.prompt_packages: list[dict[str, object]] = []

    def generate(self, prompt_package: dict[str, object]) -> str:
        self.prompt_packages.append(prompt_package)
        if len(self.prompt_packages) <= len(self.responses):
            response = self.responses[len(self.prompt_packages) - 1]
        else:
            response = self.responses[-1]
        return json.dumps(response)

    def repair(self, request_payload: dict[str, object]) -> str:
        if self.responses:
            return json.dumps(self.responses[-1])
        return json.dumps({})


class StaticIntentExtractor:
    def __init__(self, intent: IntentDocument) -> None:
        self.intent = intent
        self.calls: list[dict[str, object]] = []

    def extract(
        self,
        *,
        prompt: str,
        evidence: list[dict[str, object]],
        attachment_media: list[dict[str, object]],
        current_date: str,
        timezone: str,
    ) -> IntentDocument:
        self.calls.append(
            {
                "prompt": prompt,
                "evidence": evidence,
                "attachment_media": attachment_media,
                "current_date": current_date,
                "timezone": timezone,
            }
        )
        return self.intent


class StaticAttachmentFactExtractor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def enrich(
        self,
        *,
        prompt: str,
        evidence: list[dict[str, object]],
        attachment_media: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "prompt": prompt,
                "evidence": evidence,
                "attachment_media": attachment_media,
            }
        )
        enriched = []
        for attachment in evidence:
            enriched.append(
                {
                    **attachment,
                    "documentType": "supplier_invoice",
                    "factSummary": "Supplier invoice from ACME AS",
                    "structuredFacts": {
                        "supplierName": "ACME AS",
                        "invoiceNumber": "1001",
                        "grossAmount": 1250.0,
                    },
                    "extractedFactHints": [
                        "supplierName=ACME AS",
                        "invoiceNumber=1001",
                        "grossAmount=1250.0",
                    ],
                    "factExtractionWarnings": [],
                    "factExtractionConfidence": 0.95,
                }
            )
        return enriched


class LLMPlannerTests(unittest.TestCase):
    def _request(self, prompt: str, *, files: list[SolveFile] | None = None) -> SolveRequest:
        return SolveRequest.model_validate(
            {
                "prompt": prompt,
                "files": files or [],
                "tripletex_credentials": {
                    "base_url": "https://example.test/v2",
                    "session_token": "token",
                },
            }
        )

    def _intent(self, **overrides: object) -> IntentDocument:
        payload: dict[str, object] = {
            "contractVersion": "tripletex.intent.v1",
            "intentSummary": "test intent",
            "taskFamilies": [],
            "targetResources": [],
            "operations": [],
            "routeHints": {
                "flowNames": [],
                "commandNames": [],
                "operationIds": [],
                "technicalFlowFamilies": [],
                "domains": [],
                "subdomains": [],
                "selectorFamilies": [],
                "payloadFamilies": [],
            },
        }
        payload.update(overrides)
        return IntentDocument.model_validate(payload)

    def test_plan_injects_candidate_contract_into_prompt_context(self) -> None:
        client = CapturingClient(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {
                    "detectedPrimaryLanguage": "nb",
                    "canonicalLanguage": "en",
                    "promptOriginal": "Hei jeg klarer ikke å finne timelisten min, kan du sjekke hvor mange timer jeg jobbet i februar",
                    "promptCanonical": "I cannot find my timesheet. Can you check how many hours I worked in February?",
                },
                "understanding": {
                    "objective": "Return total worked hours for February 2026.",
                },
                "flatBridge": {
                    "commandArguments": {
                        "TimesheetEntryTotalHours_getTotalHours": {
                            "startDate": "2026-02-01",
                            "endDate": "2026-03-01",
                        }
                    }
                },
                "executionPlan": {
                    "fallbackRawCommands": [
                        {
                            "stepId": "step_get_hours",
                            "commandType": "raw_operation",
                            "operationId": "TimesheetEntryTotalHours_getTotalHours",
                        }
                    ],
                    "stepOrder": ["step_get_hours"],
                },
                "validation": {
                    "isExecutable": True,
                },
                "completion": {
                    "completionSignals": ["Hours returned"],
                },
            }
        )
        intent_extractor = StaticIntentExtractor(
            self._intent(
                intentSummary="return total worked hours for February 2026",
                taskFamilies=["timesheet.entry.total_hours"],
                targetResources=["timesheet"],
                operations=["get_total_hours"],
                routeHints={
                    "flowNames": [],
                    "commandNames": [],
                    "operationIds": ["TimesheetEntryTotalHours_getTotalHours"],
                    "technicalFlowFamilies": ["timesheet.entry.total_hours"],
                    "domains": ["timesheet"],
                    "subdomains": ["entry"],
                    "selectorFamilies": [],
                    "payloadFamilies": [],
                },
                needsResolution=True,
                needsMutation=False,
            )
        )
        planner = LLMPlanner(client=client, intent_extractor=intent_extractor)

        bridge = planner.plan(
            self._request("Hei jeg klarer ikke å finne timelisten min, kan du sjekke hvor mange timer jeg jobbet i februar"),
            current_date="2026-03-21",
            timezone="Europe/Oslo",
            request_id="req-123",
        )

        self.assertEqual(bridge.executionPlan.fallbackRawCommands[0].operationId, "TimesheetEntryTotalHours_getTotalHours")
        self.assertEqual(len(intent_extractor.calls), 1)
        prompt_package = client.prompt_packages[0]
        context = prompt_package["context"]
        self.assertIn("The request has no attachments.", prompt_package["systemInstruction"])
        self.assertIn("request.intent is a structured routing-intent document", prompt_package["systemInstruction"])
        self.assertEqual(context["retrieval"]["backend"], "local")
        self.assertIn("candidateCommandNames", context["apiContract"])
        self.assertIn("candidateFlowNames", context["apiContract"])
        self.assertIn("TimesheetEntryTotalHours_getTotalHours", context["rawApiContract"]["candidateOperationIds"])
        self.assertLessEqual(len(context["apiContract"]["candidateCommandNames"]), 40)
        self.assertLessEqual(len(context["rawApiContract"]["candidateOperationIds"]), 120)
        self.assertEqual(
            prompt_package["responseJsonSchema"]["properties"]["validation"]["type"],
            "object",
        )
        self.assertEqual(prompt_package["referenceDocuments"][0]["name"], "candidate_openapi_bundle.json")
        self.assertEqual(prompt_package["referenceDocuments"][0]["mimeType"], "application/json")
        self.assertIn("fallbackResponseJsonSchema", prompt_package)
        self.assertLess(
            len(prompt_package["referenceDocuments"][0]["content"]),
            len(Path("docs/openapi.json").read_text(encoding="utf-8")),
        )
        self.assertEqual(prompt_package["request"]["intent"]["contractVersion"], "tripletex.intent.v1")
        raw_hours = next(item for item in context["rawOperations"] if item["operationId"] == "TimesheetEntryTotalHours_getTotalHours")
        self.assertEqual(raw_hours["inputTypes"]["employeeId"]["type"], "integer")
        self.assertTrue(raw_hours["inputTypes"]["employeeId"]["defaultToTokenOwner"])

    def test_blocked_plan_without_steps_is_accepted(self) -> None:
        client = CapturingClient(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {
                    "detectedPrimaryLanguage": "en",
                    "canonicalLanguage": "en",
                    "promptOriginal": "Pay the supplier invoice from the attachment",
                    "promptCanonical": "Pay the supplier invoice from the attachment",
                },
                "understanding": {
                    "objective": "Register supplier invoice payment.",
                    "missingData": ["supplier", "payment_type"],
                    "attachmentRequired": True,
                },
                "validation": {
                    "isExecutable": False,
                    "blockingIssues": [
                        "Supplier cannot be resolved from the provided prompt or attachments.",
                        "Payment type is missing.",
                    ],
                },
                "completion": {
                    "completionSignals": ["No execution until the missing facts are provided"],
                },
            }
        )
        intent_extractor = StaticIntentExtractor(
            self._intent(
                routeHints={
                    "flowNames": ["supplier_invoice.register_payment"],
                    "commandNames": [],
                    "operationIds": ["SupplierInvoiceAddPayment_addPayment"],
                    "technicalFlowFamilies": ["supplier_invoice.add_payment", "supplier_invoice.payment"],
                    "domains": ["supplier_invoice"],
                    "subdomains": ["root"],
                    "selectorFamilies": ["supplier_invoice_selector"],
                    "payloadFamilies": ["payment_spec"],
                },
                needsMutation=True,
                needsResolution=True,
                attachmentRelevant=True,
            )
        )
        planner = LLMPlanner(client=client, intent_extractor=intent_extractor)

        bridge = planner.plan(
            self._request("Pay the supplier invoice from the attachment"),
            current_date="2026-03-21",
            timezone="Europe/Oslo",
            request_id="req-blocked",
        )

        self.assertFalse(bridge.validation.isExecutable)
        self.assertEqual(bridge.executionPlan.selectedFlows, [])
        self.assertEqual(bridge.executionPlan.selectedCommands, [])
        self.assertEqual(bridge.executionPlan.fallbackRawCommands, [])
        self.assertEqual(len(client.prompt_packages), 2)
        self.assertIsNotNone(client.prompt_packages[1]["request"]["replanFeedback"])

    def test_attachment_route_without_files_is_demoted_to_blocked_plan(self) -> None:
        client = CapturingClient(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {
                    "detectedPrimaryLanguage": "en",
                    "canonicalLanguage": "en",
                    "promptOriginal": "Bookkeep the attachment",
                    "promptCanonical": "Bookkeep the attachment",
                },
                "understanding": {
                    "objective": "Import voucher from attachment.",
                },
                "flatBridge": {
                    "commandArguments": {
                        "ledger.voucher.import_document": {
                            "attachment_id": "attachment_1",
                            "description": "Bookkeep attachment",
                        }
                    }
                },
                "executionPlan": {
                    "selectedCommands": [
                        {
                            "stepId": "step_1",
                            "commandName": "ledger.voucher.import_document",
                            "commandType": "friendly_alias",
                        }
                    ]
                },
                "validation": {
                    "isExecutable": True,
                },
                "completion": {
                    "completionSignals": ["Voucher imported"],
                },
            }
        )
        intent_extractor = StaticIntentExtractor(
            self._intent(
                routeHints={
                    "flowNames": ["supplier_invoice.import_from_attachment"],
                    "commandNames": ["ledger.voucher.import_document"],
                    "operationIds": ["LedgerVoucherImportDocument_importDocument"],
                    "technicalFlowFamilies": ["ledger.voucher.create"],
                    "domains": ["ledger"],
                    "subdomains": ["voucher"],
                    "selectorFamilies": [],
                    "payloadFamilies": [],
                },
                needsMutation=True,
                needsResolution=True,
                attachmentRelevant=True,
            )
        )
        planner = LLMPlanner(client=client, intent_extractor=intent_extractor)

        bridge = planner.plan(
            self._request("Bookkeep the attachment"),
            current_date="2026-03-21",
            timezone="Europe/Oslo",
            request_id="req-attachment-blocked",
        )

        self.assertFalse(bridge.validation.isExecutable)
        self.assertTrue(any("attachment-dependent" in issue for issue in bridge.validation.blockingIssues))

    def test_planner_accepts_structured_blocking_issue_objects_from_model(self) -> None:
        client = CapturingClient(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {
                    "detectedPrimaryLanguage": "en",
                    "canonicalLanguage": "en",
                    "promptOriginal": "Bookkeep the attachment",
                    "promptCanonical": "Bookkeep the attachment",
                },
                "understanding": {
                    "objective": "Bookkeep the attachment.",
                },
                "validation": {
                    "isExecutable": False,
                    "blockingIssues": [
                        {
                            "level": "error",
                            "code": "missing_required_input",
                            "message": "The prompt asks to bookkeep an attachment, but no attachment was provided.",
                            "blockingInputs": ["attachment_id"],
                        }
                    ],
                },
                "completion": {
                    "completionSignals": ["No execution until an attachment is provided"],
                },
            }
        )
        intent_extractor = StaticIntentExtractor(
            self._intent(
                routeHints={
                    "flowNames": ["supplier_invoice.import_from_attachment"],
                    "commandNames": ["ledger.voucher.import_document"],
                    "operationIds": ["LedgerVoucherImportDocument_importDocument"],
                    "technicalFlowFamilies": ["ledger.voucher.create"],
                    "domains": ["ledger"],
                    "subdomains": ["voucher"],
                    "selectorFamilies": [],
                    "payloadFamilies": [],
                },
                needsMutation=True,
                needsResolution=True,
                attachmentRelevant=True,
            )
        )
        planner = LLMPlanner(client=client, intent_extractor=intent_extractor)

        bridge = planner.plan(
            self._request("Bookkeep the attachment"),
            current_date="2026-03-21",
            timezone="Europe/Oslo",
            request_id="req-attachment-issue-shape",
        )

        self.assertFalse(bridge.validation.isExecutable)
        self.assertEqual(
            bridge.validation.blockingIssues,
            ["The prompt asks to bookkeep an attachment, but no attachment was provided."],
        )

    def test_plan_passes_structured_attachment_facts_into_bridge_prompt(self) -> None:
        client = CapturingClient(
            {
                "contractVersion": "tripletex.llm_bridge.v1",
                "language": {
                    "detectedPrimaryLanguage": "en",
                    "canonicalLanguage": "en",
                    "promptOriginal": "Bookkeep the attached supplier invoice",
                    "promptCanonical": "Bookkeep the attached supplier invoice",
                },
                "understanding": {
                    "objective": "Bookkeep the attached supplier invoice.",
                    "attachmentRequired": True,
                },
                "validation": {
                    "isExecutable": False,
                    "blockingIssues": ["Supplier invoice facts were extracted, but legal booking data is still incomplete."],
                },
                "completion": {
                    "completionSignals": ["No execution until the remaining accounting fields are resolved"],
                },
            }
        )
        extractor = StaticAttachmentFactExtractor()
        intent_extractor = StaticIntentExtractor(
            self._intent(
                routeHints={
                    "flowNames": ["supplier_invoice.import_from_attachment"],
                    "commandNames": [],
                    "operationIds": ["LedgerVoucherImportDocument_importDocument"],
                    "technicalFlowFamilies": ["ledger.voucher.create"],
                    "domains": ["supplier_invoice", "ledger"],
                    "subdomains": ["voucher"],
                    "selectorFamilies": ["supplier_selector"],
                    "payloadFamilies": [],
                },
                needsMutation=True,
                needsResolution=True,
                attachmentRelevant=True,
            )
        )
        planner = LLMPlanner(
            client=client,
            attachment_fact_extractor=extractor,
            intent_extractor=intent_extractor,
        )
        request = self._request(
            "Bookkeep the attached supplier invoice",
            files=[
                SolveFile(
                    filename="invoice.txt",
                    mime_type="text/plain",
                    content_base64=base64.b64encode(
                        b"Supplier: ACME AS\nInvoice: 1001\nTotal: 1250 NOK"
                    ).decode("ascii"),
                )
            ],
        )

        planner.plan(
            request,
            current_date="2026-03-21",
            timezone="Europe/Oslo",
            request_id="req-attachment-facts",
        )

        self.assertEqual(len(extractor.calls), 1)
        prompt_package = client.prompt_packages[0]
        self.assertIn("request.attachmentFacts", prompt_package["systemInstruction"])
        attachment_facts = prompt_package["request"]["attachmentFacts"]
        self.assertEqual(attachment_facts[0]["structuredFacts"]["invoiceNumber"], "1001")
        self.assertIn("invoiceNumber=1001", attachment_facts[0]["factHints"])

    def test_blocked_plan_retry_adds_replan_feedback(self) -> None:
        client = CapturingClient(
            [
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {
                        "detectedPrimaryLanguage": "en",
                        "canonicalLanguage": "en",
                        "promptOriginal": "Register payment for invoice 1001",
                        "promptCanonical": "Register payment for invoice 1001",
                    },
                    "understanding": {
                        "objective": "Register invoice payment.",
                    },
                    "validation": {
                        "isExecutable": False,
                        "blockingIssues": ["No available tools found."],
                    },
                    "completion": {
                        "completionSignals": ["No execution"],
                    },
                },
                {
                    "contractVersion": "tripletex.llm_bridge.v1",
                    "language": {
                        "detectedPrimaryLanguage": "en",
                        "canonicalLanguage": "en",
                        "promptOriginal": "Register payment for invoice 1001",
                        "promptCanonical": "Register payment for invoice 1001",
                    },
                    "understanding": {
                        "objective": "Register invoice payment.",
                    },
                    "executionPlan": {
                        "selectedFlows": [
                            {
                                "stepId": "flow_1",
                                "flowName": "invoice.register_payment",
                                "inputs": {
                                    "invoice_selector": {"invoice_number": "1001"},
                                    "payment_spec": {
                                        "payment_date": "2026-03-21",
                                        "payment_type_ref": {"id": 7},
                                        "paid_amount": 1250.0,
                                    },
                                },
                            }
                        ],
                        "stepOrder": ["flow_1"],
                    },
                    "validation": {
                        "isExecutable": True,
                    },
                    "completion": {
                        "completionSignals": ["Payment registered"],
                    },
                },
            ]
        )
        intent_extractor = StaticIntentExtractor(
            self._intent(
                routeHints={
                    "flowNames": ["invoice.register_payment"],
                    "commandNames": [],
                    "operationIds": ["InvoicePayment_payment"],
                    "technicalFlowFamilies": ["invoice.payment"],
                    "domains": ["invoice"],
                    "subdomains": ["root"],
                    "selectorFamilies": ["invoice_selector"],
                    "payloadFamilies": ["payment_spec"],
                },
                needsMutation=True,
                needsResolution=True,
            )
        )
        planner = LLMPlanner(client=client, intent_extractor=intent_extractor)

        bridge = planner.plan(
            self._request("Register payment for invoice 1001"),
            current_date="2026-03-21",
            timezone="Europe/Oslo",
            request_id="req-retry",
        )

        self.assertTrue(bridge.validation.isExecutable)
        self.assertEqual(bridge.executionPlan.selectedFlows[0].flowName, "invoice.register_payment")
        self.assertEqual(len(client.prompt_packages), 2)
        self.assertIsNone(client.prompt_packages[0]["request"]["replanFeedback"])
        self.assertEqual(
            client.prompt_packages[1]["request"]["replanFeedback"]["reason"],
            "blocked_without_route_selection",
        )


if __name__ == "__main__":
    unittest.main()
