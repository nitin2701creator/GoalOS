"""Purchase-order intelligence extractor for the Knowledge Ingestion Engine."""

from __future__ import annotations

import re
from typing import Any


class PurchaseOrderExtractor:
    """Extract structured business data from purchase-order text."""

    name = "purchase_order_extractor"

    def extract(self, raw_text: str) -> dict[str, Any]:
        """Extract common purchase-order fields from OCR or parsed text."""

        text = raw_text.strip()

        po_number = self._extract_first(
            text,
            (
                r"(?:purchase\s*order|p\.?\s*o\.?|po)\s*"
                r"(?:no|number|#)\.?\s*[:\-]?\s*"
                r"([A-Z0-9][A-Z0-9/_\-]*)",
                r"(?:purchase\s*order|p\.?\s*o\.?|po)\s*[:\-]\s*"
                r"([A-Z0-9][A-Z0-9/_\-]*)",
            ),
        )

        po_date = self._extract_first(
            text,
            (
                r"(?:purchase\s*order\s*date|po\s*date|order\s*date|date)"
                r"\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                r"(?:purchase\s*order\s*date|po\s*date|order\s*date|date)"
                r"\s*[:\-]?\s*(\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            ),
        )

        subtotal = self._extract_amount(
            text,
            (
                r"(?:sub\s*total|subtotal|taxable\s*(?:amount|value))"
                r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d{1,2})?)",
            ),
        )

        tax = self._extract_amount(
            text,
            (
                r"(?:total\s*tax|tax\s*amount|tax)"
                r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d{1,2})?)",
            ),
        )

        gst = self._extract_amount(
            text,
            (
                r"(?:gst\s*(?:amount)?|igst|cgst\s*\+\s*sgst)"
                r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d{1,2})?)",
            ),
        )

        total_amount = self._extract_amount(
            text,
            (
                r"(?:order\s*total|purchase\s*order\s*total|total\s*amount|"
                r"grand\s*total|amount\s*payable|\btotal\b)"
                r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d{1,2})?)",
            ),
        )

        currency = self._detect_currency(text)
        supplier = self._extract_supplier(text)

        extracted_values = (
            supplier,
            po_number,
            po_date,
            currency,
            subtotal,
            tax,
            gst,
            total_amount,
        )

        found = sum(value is not None for value in extracted_values)
        confidence = round(found / len(extracted_values), 2)

        return {
            "document_kind": "purchase_order",
            "status": "extracted",
            "supplier": supplier,
            "po_number": po_number,
            "po_date": po_date,
            "currency": currency,
            "subtotal": subtotal,
            "tax": tax,
            "gst": gst,
            "total_amount": total_amount,
            "confidence": confidence,
            "raw_text": raw_text,
        }

    @staticmethod
    def _extract_first(
        text: str,
        patterns: tuple[str, ...],
    ) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @classmethod
    def _extract_amount(
        cls,
        text: str,
        patterns: tuple[str, ...],
    ) -> float | None:
        value = cls._extract_first(text, patterns)

        if value is None:
            return None

        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _detect_currency(text: str) -> str | None:
        lowered = text.lower()

        if "₹" in text or "inr" in lowered or re.search(r"\brs\.?\s", lowered):
            return "INR"

        if "$" in text or "usd" in lowered:
            return "USD"

        if "€" in text or "eur" in lowered:
            return "EUR"

        if "£" in text or "gbp" in lowered:
            return "GBP"

        return None

    @classmethod
    def _extract_supplier(cls, text: str) -> str | None:
        supplier = cls._extract_first(
            text,
            (
                r"(?:supplier|vendor)(?:\s*name)?\s*[:\-]\s*([^\n]+)",
            ),
        )

        if supplier is not None:
            # Remove trailing punctuation (e.g., period) and extra whitespace.
            supplier = supplier.strip().rstrip(".")
            return supplier if supplier else None

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        for line in lines[:5]:
            if cls._is_metadata_line(line):
                continue

            if len(line) <= 120:
                # Clean up possible trailing punctuation.
                return line.rstrip(".")
        return None

    @staticmethod
    def _is_metadata_line(line: str) -> bool:
        lowered = line.lower()

        return (
            lowered in {"purchase order", "purchase order document", "po"}
            or bool(
                re.match(
                    r"(?:purchase\s*order|p\.?\s*o\.?|po)\s*"
                    r"(?:no|number|#|date)\b",
                    lowered,
                )
            )
            or bool(re.match(r"(?:order\s*date|date)\b", lowered))
        )
