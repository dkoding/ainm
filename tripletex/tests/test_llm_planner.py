from __future__ import annotations

import base64
import json
import unittest

from app.contracts.solve import SolveFile
from app.contracts.solve import SolveRequest
from app.llm import LLMPlanner


class CapturingClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.prompt_packages: list[dict[str, object]] = []

    def generate(self, prompt_package: dict[str, object]) -> str:
        self.prompt_packages.append(prompt_package)
        return json.dumps(self.response)


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

    def test_plan_injects_complete_contract_into_prompt_context(self) -> None:
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
        planner = LLMPlanner(client=client)

        bridge = planner.plan(
            self._request("Hei jeg klarer ikke å finne timelisten min, kan du sjekke hvor mange timer jeg jobbet i februar"),
            current_date="2026-03-21",
            timezone="Europe/Oslo",
            request_id="req-123",
        )

        self.assertEqual(bridge.executionPlan.fallbackRawCommands[0].operationId, "TimesheetEntryTotalHours_getTotalHours")
        prompt_package = client.prompt_packages[0]
        context = prompt_package["context"]
        self.assertIn("The request has no attachments.", prompt_package["systemInstruction"])
        self.assertIn("supplier.search", context["apiContract"]["legalCommandNames"])
        self.assertIn("supplier_invoice.import_from_attachment", context["apiContract"]["legalFlowNames"])
        self.assertIn("TimesheetEntryTotalHours_getTotalHours", context["rawApiContract"]["legalOperationIds"])
        self.assertIn("attachment_accounting", context["policyCatalog"])
        self.assertIn("employee_selector", context["selectorFamilies"])
        self.assertIn("travel_details", context["payloadFamilies"])
        self.assertIn("inputSemantics", context["apiContract"]["legalFlows"][0])
        raw_hours = next(item for item in context["rawOperations"] if item["operationId"] == "TimesheetEntryTotalHours_getTotalHours")
        self.assertEqual(raw_hours["inputTypes"]["employeeId"]["type"], "integer")
        self.assertTrue(raw_hours["inputTypes"]["employeeId"]["defaultToTokenOwner"])
        project_create = next(
            item for item in context["apiContract"]["legalCommands"] if item["commandName"] == "project.create"
        )
        self.assertEqual(project_create["inputTypeHints"]["customer_ref"]["type"], "object")

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
        planner = LLMPlanner(client=client)

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
        planner = LLMPlanner(client=client)

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
        planner = LLMPlanner(client=client)

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
        planner = LLMPlanner(client=client, attachment_fact_extractor=extractor)
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


if __name__ == "__main__":
    unittest.main()
