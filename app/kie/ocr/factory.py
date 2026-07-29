"""Construction of the OCR provider chain."""

from __future__ import annotations

from app.kie.ocr.base_ocr import OCRProvider
from app.kie.ocr.mock_provider import MockOCRProvider
from app.kie.ocr.paddle_provider import PaddleOCRProvider
from app.kie.ocr.tesseract_provider import TesseractProvider


class OCRFactory:
    """Factory responsible for constructing OCR providers."""

    _PROVIDER_CLASSES = (
        PaddleOCRProvider,
        TesseractProvider,
        MockOCRProvider,
    )

    @classmethod
    def create_providers(cls) -> tuple[OCRProvider, ...]:
        """Create providers in priority order."""
        return tuple(provider() for provider in cls._PROVIDER_CLASSES)

    @classmethod
    def create_default_providers(cls) -> tuple[OCRProvider, ...]:
        """Return the standard provider chain."""
        return cls.create_providers()

    @classmethod
    def create_provider(cls, engine_name: str) -> OCRProvider:
        """Create a provider by engine name."""
        for provider in cls.create_providers():
            if provider.engine_name().lower() == engine_name.lower():
                return provider

        raise ValueError(f"Unknown OCR provider: {engine_name}")