"""Convenient exports for all built-in OCR providers."""

from app.kie.ocr.base_ocr import OCRProvider, OCRResult
from app.kie.ocr.mock_provider import MockOCRProvider
from app.kie.ocr.paddle_provider import PaddleOCRProvider
from app.kie.ocr.tesseract_provider import TesseractProvider

__all__ = [
    "OCRProvider",
    "OCRResult",
    "MockOCRProvider",
    "PaddleOCRProvider",
    "TesseractProvider",
]