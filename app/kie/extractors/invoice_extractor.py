"""Placeholder invoice extraction."""

from __future__ import annotations

from typing import Any


class InvoiceExtractor:
    name = "invoice_extractor"

    def extract(self, raw_text: str) -> dict[str, Any]:
        return {"document_kind": "invoice", "status": "placeholder", "raw_text": raw_text}
