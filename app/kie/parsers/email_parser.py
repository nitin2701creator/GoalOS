"""Placeholder email parser."""

from pathlib import Path

from app.kie.parsers.base_parser import BaseParser


class EmailParser(BaseParser):
    name = "email_parser"
    extensions = {".eml", ".msg"}

    def supports(self, file_path: str | Path) -> bool:
        return Path(file_path).suffix.lower() in self.extensions

    def parse(self, file_path: str | Path) -> str:
        return f"[Placeholder email text extracted from {Path(file_path).name}]"
