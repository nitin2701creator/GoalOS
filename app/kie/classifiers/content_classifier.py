"""Business document classification based on extracted text."""

from __future__ import annotations

from app.kie.models import DocumentType


class ContentClassifier:
    """Classify business document meaning from extracted text."""

    _keywords = {
        DocumentType.INVOICE: (
            "invoice",
            "invoice number",
            "invoice no",
            "tax invoice",
            "bill to",
            "amount due",
        ),
        DocumentType.RECEIPT: (
            "receipt",
            "payment received",
        ),
        DocumentType.BANK_STATEMENT: (
            "bank statement",
            "account statement",
            "opening balance",
            "closing balance",
        ),
        DocumentType.PURCHASE_ORDER: (
            "purchase order",
            "po number",
            "po no",
        ),
    }

    def classify(self, raw_text: str) -> DocumentType:
        """Return the most likely business document type."""

        text = raw_text.lower()

        for document_type, keywords in self._keywords.items():
            if any(keyword in text for keyword in keywords):
                return document_type

        return DocumentType.UNKNOWN