"""Pluggable, dependency-safe OCR support for KIE."""

from app.kie.ocr.base_ocr import BaseOCR, OCRProvider, OCRResult
from app.kie.ocr.factory import OCRFactory
from app.kie.ocr.mock_provider import MockOCRProvider
from app.kie.ocr.paddle_provider import PaddleOCRProvider
from app.kie.ocr.router import OCRRouter, PlaceholderOCR
from app.kie.ocr.tesseract_provider import TesseractProvider

__all__ = [
    "BaseOCR", "OCRFactory", "OCRProvider", "OCRResult", "OCRRouter",
    "MockOCRProvider", "PaddleOCRProvider", "PlaceholderOCR", "TesseractProvider",
]
