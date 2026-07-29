"""Tests for GoalOS invoice validation."""

import pytest

from app.kie.validators.invoice_validator import (
    InvoiceValidationStatus,
    InvoiceValidator,
)


def make_invoice(**overrides):
    invoice = {
        "vendor": "Organigram",
        "invoice_number": "INV-1001",
        "invoice_date": "25/07/2026",
        "currency": "INR",
        "subtotal": 1000.0,
        "tax": 180.0,
        "gst": None,
        "grand_total": 1180.0,
        "confidence": 0.9,
    }
    invoice.update(overrides)
    return invoice


def test_valid_invoice_passes_validation():
    validator = InvoiceValidator()

    result = validator.validate(make_invoice())

    assert result.status is InvoiceValidationStatus.VALID
    assert result.is_valid is True
    assert result.issues == []
    assert result.warnings == []


@pytest.mark.parametrize(
    "field_name",
    [
        "vendor",
        "invoice_number",
        "invoice_date",
        "grand_total",
    ],
)
def test_missing_required_field_is_invalid(field_name):
    validator = InvoiceValidator()
    invoice = make_invoice(**{field_name: None})

    result = validator.validate(invoice)

    assert result.status is InvoiceValidationStatus.INVALID
    assert result.is_valid is False
    assert any(field_name in issue for issue in result.issues)


def test_incorrect_total_is_invalid():
    validator = InvoiceValidator()

    result = validator.validate(
        make_invoice(grand_total=1200.0)
    )

    assert result.status is InvoiceValidationStatus.INVALID
    assert result.is_valid is False
    assert "Invoice total does not match subtotal plus tax." in result.issues


def test_gst_is_used_when_tax_is_missing():
    validator = InvoiceValidator()

    result = validator.validate(
        make_invoice(
            tax=None,
            gst=180.0,
            grand_total=1180.0,
        )
    )

    assert result.status is InvoiceValidationStatus.VALID
    assert result.is_valid is True


def test_negative_amount_is_invalid():
    validator = InvoiceValidator()

    result = validator.validate(
        make_invoice(subtotal=-1000.0)
    )

    assert result.status is InvoiceValidationStatus.INVALID
    assert result.is_valid is False
    assert any("negative" in issue for issue in result.issues)


def test_low_confidence_requires_review():
    validator = InvoiceValidator(minimum_confidence=0.5)

    result = validator.validate(
        make_invoice(confidence=0.25)
    )

    assert result.status is InvoiceValidationStatus.REVIEW_REQUIRED
    assert result.is_valid is False
    assert result.issues == []
    assert len(result.warnings) == 1


def test_missing_confidence_requires_review():
    validator = InvoiceValidator()

    result = validator.validate(
        make_invoice(confidence=None)
    )

    assert result.status is InvoiceValidationStatus.REVIEW_REQUIRED
    assert result.is_valid is False
    assert len(result.warnings) == 1


def test_amount_tolerance_allows_small_rounding_difference():
    validator = InvoiceValidator(amount_tolerance=0.05)

    result = validator.validate(
        make_invoice(grand_total=1180.03)
    )

    assert result.status is InvoiceValidationStatus.VALID
    assert result.is_valid is True


def test_invalid_amount_tolerance_is_rejected():
    with pytest.raises(ValueError):
        InvoiceValidator(amount_tolerance=-0.01)


def test_invalid_confidence_threshold_is_rejected():
    with pytest.raises(ValueError):
        InvoiceValidator(minimum_confidence=1.1)