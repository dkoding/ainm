from __future__ import annotations

import json
import unittest

from app.benchmark import AttachmentProfile, FamilySelector, NormalizedRequest, TaskRegistry, normalize_text, tokenize_text


class StubClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def generate(self, prompt_package: dict[str, object]) -> str:
        return json.dumps(self.payload)


def _request(prompt: str, *, attachments: tuple[AttachmentProfile, ...] = ()) -> NormalizedRequest:
    return NormalizedRequest(
        prompt=prompt,
        prompt_normalized=normalize_text(prompt),
        prompt_tokens=tokenize_text(prompt),
        attachments=attachments,
        attachment_media=(),
    )


def _attachment(document_type: str) -> AttachmentProfile:
    return AttachmentProfile(
        attachment_id="attachment_1",
        filename="document.pdf",
        mime_type="application/pdf",
        byte_size=1024,
        document_type=document_type,
        summary="Supplier invoice from ACME AS",
        extracted_text="Invoice 1001 from ACME AS",
        fact_hints=("supplierName=ACME AS",),
        structured_facts={"supplierName": "ACME AS"},
        warnings=(),
        supports_multimodal=True,
    )


class FamilySelectorTests(unittest.TestCase):
    def test_selector_uses_llm_candidates_without_static_language_tables(self) -> None:
        selector = FamilySelector(
            registry=TaskRegistry(),
            client=StubClient(
                {
                    "candidates": [
                        {
                            "familyId": "employee.create_with_access",
                            "confidence": 0.93,
                            "reasons": ["The prompt asks for a new employee with administrator access."],
                            "matchedFields": ["first_name", "last_name", "user_type"],
                        }
                    ]
                }
            ),
        )

        candidates = selector.select(_request("Create employee Ola Nordmann and give him administrator access"))

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].family_id, "employee.create_with_access")
        self.assertGreater(candidates[0].confidence, 0.9)

    def test_selector_accepts_attachment_context(self) -> None:
        selector = FamilySelector(
            registry=TaskRegistry(),
            client=StubClient(
                {
                    "candidates": [
                        {
                            "familyId": "supplier_invoice.import_from_attachment",
                            "confidence": 0.88,
                            "reasons": ["The task is to import a supplier invoice from an attachment."],
                            "matchedFields": ["attachment_id"],
                        }
                    ]
                }
            ),
        )

        candidates = selector.select(
            _request("Bookkeep the attached invoice", attachments=(_attachment("supplier_invoice"),))
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].family_id, "supplier_invoice.import_from_attachment")


if __name__ == "__main__":
    unittest.main()
