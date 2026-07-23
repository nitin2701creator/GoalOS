"""Safe placeholder for a future Tesseract integration."""

from __future__ import annotations

from pathlib import Path
from shutil import which

from app.kie.ocr.base_ocr import OCRProvider, OCRResult


class TesseractProvider(OCRProvider):
    """
    Placeholder implementation for Tesseract OCR.

    The provider becomes automatically available once the
    Tesseract executable is installed on the production KVM server.
    """

    def available(self) -> bool:
        """Return True when the Tesseract executable is available."""
        return which("tesseract") is not None

    def extract_text(self, file_path: str | Path) -> OCRResult:
        """
        Placeholder OCR implementation.

        This will be replaced with the real pytesseract
        integration during the deployment sprint.
        """
        path = Path(file_path)

        return OCRResult(
            text=f"[Tesseract placeholder text extracted from {path.name}]",
            confidence=0.0,
            engine=self.engine_name(),
            metadata={
                "provider": "tesseract",
                "placeholder": True,
                "filename": path.name,
            },
        )

    def engine_name(self) -> str:
        """Return the OCR engine name."""
        return "tesseract"