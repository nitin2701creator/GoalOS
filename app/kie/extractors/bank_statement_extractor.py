"""Placeholder bank-statement extraction."""

from __future__ import annotations

from typing import Any


class BankStatementExtractor:
    name = "bank_statement_extractor"

    def extract(self, raw_text: str) -> dict[str, Any]:
        return {"document_kind": "bank_statement", "status": "placeholder", "raw_text": raw_text}
