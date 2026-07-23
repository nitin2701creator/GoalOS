"""Safe placeholder for a future PaddleOCR integration."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

from app.kie.ocr.base_ocr import OCRProvider, OCRResult


class PaddleOCRProvider(OCRProvider):
    """
    Placeholder implementation for PaddleOCR.

    The provider becomes automatically available once the
    optional ``paddleocr`` package is installed on the
    production KVM server.
    """

    def available(self) -> bool:
        """Return True when PaddleOCR is installed."""
        return find_spec("paddleocr") is not None

    def extract_text(self, file_path: str | Path) -> OCRResult:
        """
        Placeholder OCR implementation.

        This will be replaced with the real PaddleOCR
        integration during the deployment sprint.
        """
        path = Path(file_path)

        return OCRResult(
            text=f"[PaddleOCR placeholder text extracted from {path.name}]",
            confidence=0.0,
            engine=self.engine_name(),
            metadata={
                "provider": "paddleocr",
                "placeholder": True,
                "filename": path.name,
            },
        )

    def engine_name(self) -> str:
        """Return the OCR engine name."""
        return "paddleocr"