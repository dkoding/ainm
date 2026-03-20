from __future__ import annotations

from pathlib import Path
from typing import Any

from .tasking import AttachmentContext


TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/csv",
}
PDF_MIME_TYPE = "application/pdf"
ATTACHMENT_EXCERPT_CHARS = 4000


def prepare_attachments(saved_attachments: list[dict[str, Any]]) -> list[AttachmentContext]:
    prepared: list[AttachmentContext] = []
    for attachment in saved_attachments:
        prepared.append(_prepare_attachment(attachment))
    return prepared


def _prepare_attachment(saved_attachment: dict[str, Any]) -> AttachmentContext:
    path = Path(str(saved_attachment["path"]))
    mime_type = str(saved_attachment["mime_type"])
    media_kind = _classify_media_kind(mime_type=mime_type, path=path)
    notes: list[str] = []
    text_excerpt = ""

    if media_kind == "text":
        text_excerpt = _extract_text_excerpt(path, notes)
    elif media_kind == "pdf":
        text_excerpt = _extract_pdf_excerpt(path, notes)
    elif media_kind == "image":
        notes.append("Binary image is available for multimodal Gemini analysis.")
    else:
        notes.append("No extractor configured for this attachment type.")

    return AttachmentContext(
        filename=str(saved_attachment["filename"]),
        mime_type=mime_type,
        media_kind=media_kind,
        path=str(path),
        size_bytes=int(saved_attachment["size_bytes"]),
        text_excerpt=text_excerpt,
        extraction_notes=notes,
    )


def _classify_media_kind(*, mime_type: str, path: Path) -> str:
    if mime_type == PDF_MIME_TYPE or path.suffix.lower() == ".pdf":
        return "pdf"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith(TEXT_MIME_PREFIXES) or mime_type in TEXT_MIME_TYPES:
        return "text"
    if path.suffix.lower() in {".txt", ".csv", ".json", ".xml", ".md"}:
        return "text"
    return "other"


def _extract_text_excerpt(path: Path, notes: list[str]) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            content = path.read_text(encoding=encoding)
            if encoding != "utf-8":
                notes.append(f"Decoded text with {encoding}.")
            return _truncate_text(content)
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            notes.append(f"Failed to read text attachment: {exc}")
            return ""
    notes.append("Could not decode text attachment with supported encodings.")
    return ""


def _extract_pdf_excerpt(path: Path, notes: list[str]) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        notes.append("pypdf is not installed, so PDF text extraction is unavailable.")
        return ""

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # pragma: no cover - parser failures depend on file content
        notes.append(f"Failed to open PDF: {exc}")
        return ""

    chunks: list[str] = []
    remaining_chars = ATTACHMENT_EXCERPT_CHARS
    for page_number, page in enumerate(reader.pages, start=1):
        if remaining_chars <= 0:
            break
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:  # pragma: no cover - parser failures depend on file content
            notes.append(f"Failed to extract text from PDF page {page_number}: {exc}")
            continue
        if not page_text.strip():
            continue
        trimmed = page_text[:remaining_chars]
        chunks.append(trimmed)
        remaining_chars -= len(trimmed)

    if not chunks:
        notes.append("PDF text extraction returned no text.")
        return ""
    return _truncate_text("\n\n".join(chunks))


def _truncate_text(content: str) -> str:
    trimmed = " ".join(content.split())
    if len(trimmed) <= ATTACHMENT_EXCERPT_CHARS:
        return trimmed
    return f"{trimmed[:ATTACHMENT_EXCERPT_CHARS]}..."
