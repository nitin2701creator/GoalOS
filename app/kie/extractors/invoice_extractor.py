"""Invoice intelligence extractor for the Knowledge Ingestion Engine."""

from __future__ import annotations

import re
from typing import Any


class InvoiceExtractor:
    """Extract structured business data from invoice text."""

    name = "invoice_extractor"

    def extract(self, raw_text: str) -> dict[str, Any]:
        """Extract common invoice fields from OCR or parsed text."""

        text = raw_text.strip()

        invoice_number = self._extract_first(
            text,
            (
                r"(?:invoice\s*(?:no|number|#)\.?\s*[:\-]?\s*)([A-Z0-9][A-Z0-9/_\-]*)",
                r"(?:inv\s*(?:no|number|#)\.?\s*[:\-]?\s*)([A-Z0-9][A-Z0-9/_\-]*)",
            ),
        )

        invoice_date = self._extract_first(
            text,
            (
                r"(?:invoice\s*date|date)\s*[:\-]?\s*"
                r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                r"(?:invoice\s*date|date)\s*[:\-]?\s*"
                r"(\d{4}[/-]\d{1,2}[/-]\d{1,2})",
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

        grand_total = self._extract_amount(
            text,
            (
                r"(?:grand\s*total|invoice\s*total|total\s*amount|amount\s*payable)"
                r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d{1,2})?)",
            ),
        )

        currency = self._detect_currency(text)
        vendor = self._extract_vendor(text)

        extracted_values = (
            vendor,
            invoice_number,
            invoice_date,
            currency,
            subtotal,
            tax,
            gst,
            grand_total,
        )

        found = sum(value is not None for value in extracted_values)
        confidence = round(found / len(extracted_values), 2)

        return {
            "document_kind": "invoice",
            "status": "extracted",
            "vendor": vendor,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "currency": currency,
            "subtotal": subtotal,
            "tax": tax,
            "gst": gst,
            "grand_total": grand_total,
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

    @staticmethod
    def _extract_vendor(text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        if not lines:
            return None

        ignored = {
            "invoice",
            "tax invoice",
            "commercial invoice",
            "gst invoice",
        }

        for line in lines[:5]:
            if line.lower() not in ignored and len(line) <= 120:
                return line

        return None