"""Placeholder PDF parser."""

from pathlib import Path

from app.kie.parsers.base_parser import BaseParser


class PDFParser(BaseParser):
    name = "pdf_parser"

    def supports(self, file_path: str | Path) -> bool:
        return Path(file_path).suffix.lower() == ".pdf"

    def parse(self, file_path: str | Path) -> str:
        return f"[Placeholder PDF text extracted from {Path(file_path).name}]"
