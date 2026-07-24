"""PDF parser for the Knowledge Ingestion Engine."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from app.kie.parsers.base_parser import BaseParser


class PDFParser(BaseParser):
    """Extract text from text-based PDF documents."""

    name = "pdf_parser"

    def supports(self, file_path: str | Path) -> bool:
        return Path(file_path).suffix.lower() == ".pdf"

    def parse(self, file_path: str | Path) -> str:
        """Extract text from every page of a real PDF."""

        path = Path(file_path)
        reader = PdfReader(path)

        pages: list[str] = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())

        return "\n".join(pages)