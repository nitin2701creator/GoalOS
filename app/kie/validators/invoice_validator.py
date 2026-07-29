"""Invoice validation for the GoalOS Knowledge Ingestion Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class InvoiceValidationStatus(str, Enum):
    """Possible validation outcomes for an extracted invoice."""

    VALID = "valid"
    REVIEW_REQUIRED = "review_required"
    INVALID = "invalid"


@dataclass(frozen=True)
class InvoiceValidationResult:
    """Structured result returned by the invoice validator."""

    status: InvoiceValidationStatus
    is_valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class InvoiceValidator:
    """Validate structured invoice data extracted by GoalOS."""

    REQUIRED_FIELDS = (
        "vendor",
        "invoice_number",
        "invoice_date",
        "grand_total",
    )

    def __init__(
        self,
        amount_tolerance: float = 0.01,
        minimum_confidence: float = 0.5,
    ) -> None:
        if amount_tolerance < 0:
            raise ValueError("amount_tolerance must be zero or greater")

        if not 0 <= minimum_confidence <= 1:
            raise ValueError(
                "minimum_confidence must be between zero and one"
            )

        self.amount_tolerance = amount_tolerance
        self.minimum_confidence = minimum_confidence

    def validate(
        self,
        invoice: dict[str, Any],
    ) -> InvoiceValidationResult:
        """Validate extracted invoice fields and arithmetic."""

        issues: list[str] = []
        warnings: list[str] = []

        self._validate_required_fields(invoice, issues)
        self._validate_amounts(invoice, issues)
        self._validate_confidence(invoice, warnings)

        if issues:
            return InvoiceValidationResult(
                status=InvoiceValidationStatus.INVALID,
                is_valid=False,
                issues=issues,
                warnings=warnings,
            )

        if warnings:
            return InvoiceValidationResult(
                status=InvoiceValidationStatus.REVIEW_REQUIRED,
                is_valid=False,
                issues=issues,
                warnings=warnings,
            )

        return InvoiceValidationResult(
            status=InvoiceValidationStatus.VALID,
            is_valid=True,
            issues=issues,
            warnings=warnings,
        )

    def _validate_required_fields(
        self,
        invoice: dict[str, Any],
        issues: list[str],
    ) -> None:
        for field_name in self.REQUIRED_FIELDS:
            value = invoice.get(field_name)

            if value is None:
                issues.append(
                    f"Missing required invoice field: {field_name}."
                )
                continue

            if isinstance(value, str) and not value.strip():
                issues.append(
                    f"Missing required invoice field: {field_name}."
                )

    def _validate_amounts(
        self,
        invoice: dict[str, Any],
        issues: list[str],
    ) -> None:
        subtotal = self._number(invoice.get("subtotal"))
        tax = self._number(invoice.get("tax"))
        gst = self._number(invoice.get("gst"))
        grand_total = self._number(invoice.get("grand_total"))

        for field_name, amount in (
            ("subtotal", subtotal),
            ("tax", tax),
            ("gst", gst),
            ("grand_total", grand_total),
        ):
            if amount is not None and amount < 0:
                issues.append(
                    f"Invoice amount cannot be negative: {field_name}."
                )

        if subtotal is None or grand_total is None:
            return

        tax_component = tax

        if tax_component is None:
            tax_component = gst

        if tax_component is None:
            return

        expected_total = subtotal + tax_component

        if abs(expected_total - grand_total) > self.amount_tolerance:
            issues.append(
                "Invoice total does not match subtotal plus tax."
            )

    def _validate_confidence(
        self,
        invoice: dict[str, Any],
        warnings: list[str],
    ) -> None:
        confidence = self._number(invoice.get("confidence"))

        if confidence is None:
            warnings.append(
                "Invoice extraction confidence is unavailable."
            )
            return

        if confidence < self.minimum_confidence:
            warnings.append(
                "Invoice extraction confidence is below the review threshold."
            )

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None