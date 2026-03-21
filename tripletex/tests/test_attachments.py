from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.attachments import prepare_attachments


class AttachmentPreparationTests(unittest.TestCase):
    def test_prepare_attachments_classifies_text_image_and_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            text_path = root / "notes.txt"
            image_path = root / "receipt.png"
            pdf_path = root / "contract.pdf"

            text_path.write_text("Hello from Tripletex\nThis is a text attachment.", encoding="utf-8")
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")
            pdf_path.write_bytes(b"%PDF-1.4\n%invalid-but-classifiable\n")

            with patch("app.attachments._extract_pdf_excerpt", return_value="PDF excerpt"):
                prepared = prepare_attachments(
                    [
                        {
                            "filename": "notes.txt",
                            "mime_type": "text/plain",
                            "path": str(text_path),
                            "size_bytes": text_path.stat().st_size,
                        },
                        {
                            "filename": "receipt.png",
                            "mime_type": "image/png",
                            "path": str(image_path),
                            "size_bytes": image_path.stat().st_size,
                        },
                        {
                            "filename": "contract.pdf",
                            "mime_type": "application/pdf",
                            "path": str(pdf_path),
                            "size_bytes": pdf_path.stat().st_size,
                        },
                    ]
                )

        contexts = {item.filename: item for item in prepared}
        self.assertEqual(contexts["notes.txt"].media_kind, "text")
        self.assertIn("Hello from Tripletex", contexts["notes.txt"].text_excerpt)
        self.assertEqual(contexts["receipt.png"].media_kind, "image")
        self.assertIn("Binary image is available for multimodal Gemini analysis.", contexts["receipt.png"].extraction_notes)
        self.assertEqual(contexts["contract.pdf"].media_kind, "pdf")
        self.assertEqual(contexts["contract.pdf"].text_excerpt, "PDF excerpt")


if __name__ == "__main__":
    unittest.main()
