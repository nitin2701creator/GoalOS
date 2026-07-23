"""Route OCR work to the first available provider."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.kie.ocr.base_ocr import OCRProvider, OCRResult
from app.kie.ocr.factory import OCRFactory
from app.kie.ocr.mock_provider import MockOCRProvider


class OCRRouter:
    """Select PaddleOCR, Tesseract, then the deterministic mock fallback."""

    def __init__(self, providers: Iterable[OCRProvider] | None = None) -> None:
        self._providers = tuple(providers) if providers is not None else OCRFactory.create_providers()

    def select_provider(self) -> OCRProvider:
        """Return the first available configured provider."""

        for provider in self._providers:
            if provider.available():
                return provider
        raise RuntimeError("No OCR provider is available")

    def extract_text(self, file_path: str | Path) -> OCRResult:
        """Extract text using the selected provider."""

        return self.select_provider().extract_text(file_path)

    # Kept for callers of the original router API.
    def select_engine(self, *_: object, **__: object) -> OCRProvider:
        return self.select_provider()


# Old placeholder name remains an import-compatible alias.
PlaceholderOCR = MockOCRProvider
