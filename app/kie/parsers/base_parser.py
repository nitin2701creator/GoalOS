"""Parser contract used by the Knowledge Ingestion Engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseParser(ABC):
    """Read one or more related file formats into plain text."""

    name: str

    @abstractmethod
    def supports(self, file_path: str | Path) -> bool:
        """Return whether this parser supports the supplied file path."""

    @abstractmethod
    def parse(self, file_path: str | Path) -> str:
        """Return text extracted from the supplied file."""
