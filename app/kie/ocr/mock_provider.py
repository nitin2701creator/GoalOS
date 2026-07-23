"""Deterministic dependency-free OCR fallback."""

from __future__ import annotations

from pathlib import Path

from app.kie.ocr.base_ocr import OCRProvider, OCRResult


class MockOCRProvider(OCRProvider):
    """Fallback provider used when no production OCR engine is available."""

    def available(self) -> bool:
        return True

    def extract_text(self, file_path: str | Path) -> OCRResult:
        filename = Path(file_path).name
        return OCRResult(
            text=f"[Mock OCR text extracted from {filename}]",
            engine=self.engine_name(),
            confidence=0.0,
        )

    def engine_name(self) -> str:
        return "mock"
