"""Placeholder spreadsheet parser."""

from pathlib import Path

from app.kie.parsers.base_parser import BaseParser


class ExcelParser(BaseParser):
    name = "excel_parser"
    extensions = {".xls", ".xlsx", ".xlsm", ".csv"}

    def supports(self, file_path: str | Path) -> bool:
        return Path(file_path).suffix.lower() in self.extensions

    def parse(self, file_path: str | Path) -> str:
        return f"[Placeholder spreadsheet text extracted from {Path(file_path).name}]"
