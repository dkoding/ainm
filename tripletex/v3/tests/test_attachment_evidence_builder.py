from __future__ import annotations

import base64
import unittest

from app.contracts.solve import SolveFile
from app.llm.attachment_evidence_builder import AttachmentEvidenceBuilder


class AttachmentEvidenceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = AttachmentEvidenceBuilder()

    def test_text_attachment_includes_structured_evidence_fields(self) -> None:
        file = SolveFile(
            filename="notes.txt",
            mime_type="text/plain",
            content_base64=base64.b64encode(b"hello world").decode("ascii"),
        )

        evidence = self.builder.build([file])[0]

        self.assertEqual(evidence["attachmentId"], "attachment_1")
        self.assertEqual(evidence["extractedText"], "hello world")
        self.assertEqual(evidence["textOriginal"], "hello world")
        self.assertEqual(evidence["textCanonical"], "hello world")
        self.assertEqual(evidence["ocrText"], "")
        self.assertEqual(evidence["extractionConfidence"], 1.0)
        self.assertEqual(evidence["warnings"], [])
        self.assertEqual(evidence["provenance"]["mode"], "local_text_extract")
        self.assertFalse(evidence["provenance"]["supportsMultimodal"])

    def test_image_attachment_marks_multimodal_only_when_no_local_text_exists(self) -> None:
        file = SolveFile(
            filename="receipt.png",
            mime_type="image/png",
            content_base64=base64.b64encode(b"not-a-real-image").decode("ascii"),
        )

        evidence = self.builder.build([file])[0]

        self.assertEqual(evidence["extractedText"], "")
        self.assertEqual(evidence["ocrText"], "")
        self.assertEqual(evidence["extractionConfidence"], 0.0)
        self.assertEqual(evidence["provenance"]["mode"], "multimodal_only")
        self.assertTrue(evidence["provenance"]["supportsMultimodal"])
        self.assertIn("Gemini multimodal analysis", evidence["warnings"][0])


if __name__ == "__main__":
    unittest.main()
