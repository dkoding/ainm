from __future__ import annotations

import json
import unittest

from app.llm.attachment_fact_extractor import AttachmentFactExtractor


class StubClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt_packages: list[dict[str, object]] = []

    def generate(self, prompt_package: dict[str, object]) -> str:
        self.prompt_packages.append(prompt_package)
        return self.response


class AttachmentFactExtractorTests(unittest.TestCase):
    def test_enriches_attachment_evidence_with_structured_facts(self) -> None:
        client = StubClient(
            json.dumps(
                {
                    "attachments": [
                        {
                            "attachmentId": "attachment_1",
                            "documentType": "supplier_invoice",
                            "summary": "Supplier invoice from ACME AS",
                            "structuredFacts": {
                                "supplierName": "ACME AS",
                                "invoiceNumber": "1001",
                                "grossAmount": 1250.0,
                                "currency": "NOK",
                                "routeHints": ["supplier_invoice.import_from_attachment"],
                            },
                            "warnings": [],
                            "confidence": 0.91,
                        }
                    ]
                }
            )
        )
        extractor = AttachmentFactExtractor(client=client)
        evidence = [
            {
                "attachmentId": "attachment_1",
                "filename": "invoice.pdf",
                "mimeType": "application/pdf",
                "extractedText": "Invoice 1001\nTotal 1250 NOK",
                "warnings": [],
                "extractedFactHints": [],
                "provenance": {"mode": "local_pdf_extract"},
            }
        ]
        attachment_media = [
            {
                "attachmentId": "attachment_1",
                "filename": "invoice.pdf",
                "mimeType": "application/pdf",
                "contentBase64": "Zm9v",
            }
        ]

        enriched = extractor.enrich(
            prompt="Bookkeep the attached supplier invoice",
            evidence=evidence,
            attachment_media=attachment_media,
        )

        self.assertEqual(enriched[0]["documentType"], "supplier_invoice")
        self.assertEqual(enriched[0]["structuredFacts"]["invoiceNumber"], "1001")
        self.assertEqual(enriched[0]["factExtractionConfidence"], 0.91)
        self.assertIn("invoiceNumber=1001", enriched[0]["extractedFactHints"])
        self.assertEqual(enriched[0]["provenance"]["factExtraction"], "gemini_structured")
        self.assertEqual(client.prompt_packages[0]["media"][0]["attachmentId"], "attachment_1")
        self.assertIn("fallbackResponseJsonSchema", client.prompt_packages[0])
        self.assertEqual(
            client.prompt_packages[0]["responseJsonSchema"]["properties"]["attachments"]["type"],
            "array",
        )

    def test_invalid_json_falls_back_to_raw_attachment_evidence(self) -> None:
        extractor = AttachmentFactExtractor(client=StubClient("not json"))
        evidence = [
            {
                "attachmentId": "attachment_1",
                "filename": "receipt.png",
                "mimeType": "image/png",
                "extractedText": "",
                "warnings": ["No local text extraction is available for this attachment; rely on Gemini multimodal analysis."],
                "extractedFactHints": [],
                "provenance": {"mode": "multimodal_only"},
            }
        ]

        enriched = extractor.enrich(
            prompt="Bookkeep the attached receipt",
            evidence=evidence,
            attachment_media=[
                {
                    "attachmentId": "attachment_1",
                    "filename": "receipt.png",
                    "mimeType": "image/png",
                    "contentBase64": "Zm9v",
                }
            ],
        )

        self.assertEqual(enriched[0]["structuredFacts"], {})
        self.assertIn("Structured attachment fact extraction returned invalid JSON", enriched[0]["factExtractionWarnings"][0])

    def test_accepts_attachment_json_inside_markdown_fence(self) -> None:
        extractor = AttachmentFactExtractor(
            client=StubClient(
                """```json
                {"attachments":[{"attachmentId":"attachment_1","documentType":"supplier_invoice","summary":"Invoice","structuredFacts":{"invoiceNumber":"1001"},"warnings":[],"confidence":0.8}]}
                ```"""
            )
        )
        evidence = [
            {
                "attachmentId": "attachment_1",
                "filename": "invoice.pdf",
                "mimeType": "application/pdf",
                "extractedText": "Invoice 1001",
                "warnings": [],
                "extractedFactHints": [],
                "provenance": {"mode": "local_pdf_extract"},
            }
        ]

        enriched = extractor.enrich(
            prompt="Bookkeep the attached invoice",
            evidence=evidence,
            attachment_media=[
                {
                    "attachmentId": "attachment_1",
                    "filename": "invoice.pdf",
                    "mimeType": "application/pdf",
                    "contentBase64": "Zm9v",
                }
            ],
        )

        self.assertEqual(enriched[0]["structuredFacts"]["invoiceNumber"], "1001")
        self.assertEqual(enriched[0]["documentType"], "supplier_invoice")


if __name__ == "__main__":
    unittest.main()
