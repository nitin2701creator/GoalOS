"""
Contracts shared by OCR providers.

Every OCR implementation (PaddleOCR, Tesseract, Azure Document AI,
Gemini Vision, GPT Vision, etc.) must implement the OCRProvider
interface so the rest of GoalOS remains provider-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class OCRResult:
    """
    Standard OCR response returned by every provider.

    Backward compatible with existing GoalOS code.
    """

    text: str
    engine: str
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class OCRProvider(ABC):
    """
    Abstract base class for OCR engines.
    """

    @abstractmethod
    def engine_name(self) -> str:
        """Return the OCR engine name."""
        raise NotImplementedError

    @abstractmethod
    def available(self) -> bool:
        """Return True if this OCR provider is available."""
        raise NotImplementedError

    @abstractmethod
    def extract_text(self, file_path: str | Path) -> OCRResult:
        """
        Extract text from a document or image.

        Parameters
        ----------
        file_path
            Path to the input document.

        Returns
        -------
        OCRResult
        """
        raise NotImplementedError


# ------------------------------------------------------------------
# Backward compatibility
# ------------------------------------------------------------------

BaseOCR = OCRProvider