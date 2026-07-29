"""Placeholder receipt extraction."""

from __future__ import annotations

from typing import Any


class ReceiptExtractor:
    name = "receipt_extractor"

    def extract(self, raw_text: str) -> dict[str, Any]:
        return {"document_kind": "receipt", "status": "placeholder", "raw_text": raw_text}
