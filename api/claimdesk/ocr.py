"""Text from a document: the PDF text layer when there is one, Tesseract (Hungarian + English) for scans."""

import os
from pathlib import Path

import pytesseract
from PIL import Image
from pypdf import PdfReader

from claimdesk.config import settings


def text_of(path: Path) -> tuple[str, str]:
    """Return (text, method)."""
    if path.suffix.lower() == ".pdf":
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        if text.strip():
            return text, "pdf_text"
        raise ValueError(f"{path.name}: PDF without a text layer; rasterise it first")
    s = settings()
    pytesseract.pytesseract.tesseract_cmd = s.tesseract_cmd
    if s.tessdata_dir:
        os.environ["TESSDATA_PREFIX"] = s.tessdata_dir  # a quoted --tessdata-dir breaks on Windows paths
    return pytesseract.image_to_string(Image.open(path), lang="hun+eng", config="--psm 4"), "ocr"
