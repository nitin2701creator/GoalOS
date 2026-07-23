"""Placeholder image parser."""

from pathlib import Path

from app.kie.parsers.base_parser import BaseParser


class ImageParser(BaseParser):
    name = "image_parser"
    extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}

    def supports(self, file_path: str | Path) -> bool:
        return Path(file_path).suffix.lower() in self.extensions

    def parse(self, file_path: str | Path) -> str:
        return f"[Placeholder image text extracted from {Path(file_path).name}]"
