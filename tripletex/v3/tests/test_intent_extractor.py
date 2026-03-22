from __future__ import annotations

import json
import unittest

from app.llm.intent_extractor import IntentExtractor


class StubClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.prompt_packages: list[dict[str, object]] = []

    def generate(self, prompt_package: dict[str, object]) -> str:
        self.prompt_packages.append(prompt_package)
        return json.dumps(self.response)


class IntentExtractorTests(unittest.TestCase):
    def test_extractor_normalizes_to_known_route_hints_and_merges_attachment_hints(self) -> None:
        client = StubClient(
            {
                "contractVersion": "tripletex.intent.v1",
                "intentSummary": "register invoice payment",
                "taskFamilies": ["invoice.payment"],
                "targetResources": ["invoice"],
                "operations": ["register_payment"],
                "routeHints": {
                    "flowNames": ["invoice.register_payment", "invented.flow"],
                    "commandNames": ["invoice.register_payment", "unknown.command"],
                    "operationIds": ["InvoicePayment_payment", "UnknownOperation_post"],
                    "technicalFlowFamilies": ["invoice.payment", "unknown.family"],
                    "domains": ["invoice", "not_a_domain"],
                    "subdomains": ["root", "not_a_subdomain"],
                    "selectorFamilies": ["invoice_selector", "missing_selector"],
                    "payloadFamilies": ["payment_spec", "missing_payload"],
                },
                "needsMutation": True,
                "needsResolution": True,
                "attachmentRelevant": False,
                "confidence": 0.92,
            }
        )
        extractor = IntentExtractor(client=client)
        evidence = [
            {
                "attachmentId": "attachment_1",
                "filename": "payment.pdf",
                "mimeType": "application/pdf",
                "documentType": "invoice",
                "factSummary": "Invoice payment confirmation",
                "structuredFacts": {
                    "routeHints": ["invoice.register_payment"],
                },
                "extractedFactHints": ["invoiceNumber=1001"],
                "factExtractionWarnings": [],
            }
        ]

        intent = extractor.extract(
            prompt="Register payment for invoice 1001",
            evidence=evidence,
            attachment_media=[],
            current_date="2026-03-21",
            timezone="Europe/Oslo",
        )

        self.assertEqual(intent.contractVersion, "tripletex.intent.v1")
        self.assertEqual(intent.routeHints.flowNames, ["invoice.register_payment"])
        self.assertEqual(intent.routeHints.commandNames, ["invoice.register_payment"])
        self.assertEqual(intent.routeHints.operationIds, ["InvoicePayment_payment"])
        self.assertEqual(intent.routeHints.technicalFlowFamilies, ["invoice.payment"])
        self.assertEqual(intent.routeHints.selectorFamilies, ["invoice_selector"])
        self.assertEqual(intent.routeHints.payloadFamilies, ["payment_spec"])
        self.assertEqual(intent.routeHints.domains, ["invoice"])
        self.assertIn("intent_route_catalog.json", client.prompt_packages[0]["referenceDocuments"][0]["name"])
        self.assertIn("fallbackResponseJsonSchema", client.prompt_packages[0])
        self.assertEqual(
            client.prompt_packages[0]["responseJsonSchema"]["required"],
            ["contractVersion", "routeHints"],
        )


if __name__ == "__main__":
    unittest.main()
