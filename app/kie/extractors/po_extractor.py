"""Placeholder purchase-order extraction."""

from __future__ import annotations

from typing import Any


class PurchaseOrderExtractor:
    name = "purchase_order_extractor"

    def extract(self, raw_text: str) -> dict[str, Any]:
        return {"document_kind": "purchase_order", "status": "placeholder", "raw_text": raw_text}
