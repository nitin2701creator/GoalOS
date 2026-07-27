"""Purchase-order intelligence extractor for the Knowledge Ingestion Engine.

The extractor follows the same conventions used across the repository for
other KIE extractors (e.g. invoice_extractor).  It aims to be tolerant of
common variations in OCR‑generated purchase‑order text while still providing
a deterministic output schema that downstream services can rely on.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


class PurchaseOrderExtractor:
    """Extract structured business data from purchase‑order text."""

    name = "purchase_order_extractor"

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def extract(self, raw_text: str) -> dict[str, Any]:
        """Parse *raw_text* and return a dictionary with the extracted fields.

        The returned dictionary always contains the keys required by the
        ``PurchaseOrderExtractionResponse`` schema:

        - ``document_kind`` – constant ``"purchase_order"``.
        - ``status`` – ``"extracted"`` if at least one field could be parsed,
          otherwise ``"failed"``.
        - ``supplier``, ``po_number``, ``po_date``, ``currency``,
          ``subtotal``, ``tax``, ``gst``, ``total_amount``,
          ``confidence`` and ``raw_text``.

        ``confidence`` is a float in the range ``0.0 – 1.0`` indicating the
        proportion of fields that were successfully extracted.
        """
        text = raw_text.strip()

        # ----------------------------------------------------------------- #
        # 1️⃣  Extract individual fields using the helper methods below.
        # ----------------------------------------------------------------- #
        po_number = self._extract_first(
            text,
            (
                # “Purchase Order No: PO‑12345”, “PO‑12345”, “PO #12345” etc.
                r"(?:purchase\s*order|p\.?\s*o\.?|po)\s*"
                r"(?:no|number|#)\.?\s*[:\-]?\s*"
                r"([A-Z0-9][A-Z0-9/_\-\s]*)",
                r"(?:purchase\s*order|p\.?\s*o\.?|po)\s*[:\-]\s*"
                r"([A-Z0-9][A-Z0-9/_\-\s]*)",
            ),
        )

        po_date = self._extract_first(
            text,
            (
                # Various date formats – DD/MM/YYYY, YYYY‑MM‑DD, etc.
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

        # If the explicit total is missing, fall back to a simple sum.
        if total_amount is None and all(v is not None for v in (subtotal, tax, gst)):
            total_amount = round(subtotal + tax + gst, 2)

        currency = self._detect_currency(text)
        supplier = self._extract_supplier(text)

        # ----------------------------------------------------------------- #
        # 2️⃣  Compute confidence – proportion of non‑None fields.
        # ----------------------------------------------------------------- #
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
        found = sum(v is not None for v in extracted_values)
        confidence = round(found / len(extracted_values), 2)

        # ----------------------------------------------------------------- #
        # 3️⃣  Build the final payload.
        # ----------------------------------------------------------------- #
        return {
            "document_kind": "purchase_order",
            "status": "extracted" if found > 0 else "failed",
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

    # --------------------------------------------------------------------- #
    # Helper methods – these are deliberately static / class methods so they
    # can be unit‑tested in isolation.
    # --------------------------------------------------------------------- #
    @staticmethod
    def _extract_first(text: str, patterns: tuple[str, ...]) -> str | None:
        """Return the first captured group that matches any of *patterns*."""
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @classmethod
    def _extract_amount(cls, text: str, patterns: tuple[str, ...]) -> float | None:
        """Extract a monetary amount and convert it to ``float``."""
        raw = cls._extract_first(text, patterns)
        if raw is None:
            return None
        try:
            # Remove thousand separators and convert.
            return float(raw.replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _detect_currency(text: str) -> str | None:
        """Detect the most likely currency symbol / code in *text*."""
        lowered = text.lower()

        if "₹" in text or "inr" in lowered or re.search(r"\brs\.?\b", lowered):
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
        """Best‑effort extraction of the supplier / vendor name.

        1. Look for an explicit ``Supplier: …`` or ``Vendor: …`` line.
        2. If not found, return the first non‑metadata line (usually the
           company name at the top of the document).
        """
        # Explicit line – captures everything up to a newline.
        supplier = cls._extract_first(
            text,
            (
                r"(?:supplier|vendor)(?:\s*name)?\s*[:\-]\s*([^\n]+)",
            ),
        )
        if supplier:
            # Normalise – strip trailing punctuation and whitespace.
            return supplier.strip().rstrip(".,;:")

        # Fallback – scan the first few lines for a plausible company name.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for line in lines[:5]:
            if cls._is_metadata_line(line):
                continue
            # Avoid returning a line that looks like a date or amount.
            if re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", line):
                continue
            if re.search(r"[\d,]+\s*(?:₹|rs\.?|inr|\$|€|£)", line, flags=re.IGNORECASE):
                continue
            return line.rstrip(".,;:")
        return None

    @staticmethod
    def _is_metadata_line(line: str) -> bool:
        """Return ``True`` if *line* looks like a PO metadata header."""
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
