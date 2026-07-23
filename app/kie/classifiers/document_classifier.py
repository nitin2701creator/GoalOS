"""Lightweight document classification based on file extensions."""

from __future__ import annotations

from pathlib import Path

from app.kie.models import DocumentType


class DocumentClassifier:
    """Classify a document's container format without inspecting its contents."""

    _extension_types = {
        ".pdf": DocumentType.PDF,
        ".jpg": DocumentType.IMAGE,
        ".jpeg": DocumentType.IMAGE,
        ".png": DocumentType.IMAGE,
        ".gif": DocumentType.IMAGE,
        ".bmp": DocumentType.IMAGE,
        ".tiff": DocumentType.IMAGE,
        ".webp": DocumentType.IMAGE,
        ".xls": DocumentType.EXCEL,
        ".xlsx": DocumentType.EXCEL,
        ".xlsm": DocumentType.EXCEL,
        ".csv": DocumentType.EXCEL,
        ".eml": DocumentType.EMAIL,
        ".msg": DocumentType.EMAIL,
    }

    def classify(self, file_path: str | Path) -> DocumentType:
        """Return the general document type associated with a file extension."""

        return self._extension_types.get(Path(file_path).suffix.lower(), DocumentType.UNKNOWN)
