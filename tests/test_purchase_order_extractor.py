"""Tests for GoalOS purchase-order extraction."""

import pytest

from app.kie.extractors.po_extractor import PurchaseOrderExtractor


def test_extractor_returns_complete_structured_purchase_order() -> None:
    raw_text = """
    Supplier: ACME SUPPLIES PRIVATE LIMITED
    Purchase Order Number: PO-1001
    PO Date: 24/07/2026
    Currency: INR
    Subtotal: 1000.00
    Tax Amount: 180.00
    GST: 180.00
    Order Total: 1180.00
    """

    data = PurchaseOrderExtractor().extract(raw_text)

    assert data["document_kind"] == "purchase_order"
    assert data["status"] == "extracted"
    assert data["supplier"] == "ACME SUPPLIES PRIVATE LIMITED"
    assert data["po_number"] == "PO-1001"
    assert data["po_date"] == "24/07/2026"
    assert data["currency"] == "INR"
    assert data["subtotal"] == 1000.00
    assert data["tax"] == 180.00
    assert data["gst"] == 180.00
    assert data["total_amount"] == 1180.00
    assert data["confidence"] == 1.0
    assert data["raw_text"] == raw_text


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("PO No: PO-1002", "PO-1002"),
        ("P.O. Number: PO_1003", "PO_1003"),
        ("Purchase Order # PO/1004", "PO/1004"),
        ("Purchase Order: PO-1005", "PO-1005"),
    ],
)
def test_extractor_supports_po_number_label_variants(
    label: str,
    expected: str,
) -> None:
    data = PurchaseOrderExtractor().extract(label)

    assert data["po_number"] == expected


def test_extractor_uses_first_non_metadata_line_as_supplier() -> None:
    raw_text = """
    GLOBEX CORPORATION
    Purchase Order
    PO No: PO-1006
    Order Date: 2026-07-24
    """

    data = PurchaseOrderExtractor().extract(raw_text)

    assert data["supplier"] == "GLOBEX CORPORATION"
    assert data["po_date"] == "2026-07-24"


@pytest.mark.parametrize(
    ("currency_text", "expected"),
    [
        ("Currency: INR", "INR"),
        ("Total Amount: $100.00", "USD"),
        ("Total Amount: €100.00", "EUR"),
        ("Total Amount: £100.00", "GBP"),
    ],
)
def test_extractor_detects_currency_variants(
    currency_text: str,
    expected: str,
) -> None:
    data = PurchaseOrderExtractor().extract(currency_text)

    assert data["currency"] == expected


@pytest.mark.parametrize(
    "total_label",
    ["Order Total", "Total Amount", "Total"],
)
def test_extractor_returns_amount_fields(total_label: str) -> None:
    raw_text = f"""
    Subtotal: 1,000.00
    Tax: 100.00
    GST Amount: 80.00
    {total_label}: 1,180.00
    """

    data = PurchaseOrderExtractor().extract(raw_text)

    assert data["subtotal"] == 1000.00
    assert data["tax"] == 100.00
    assert data["gst"] == 80.00
    assert data["total_amount"] == 1180.00


def test_extractor_handles_missing_optional_fields_and_confidence() -> None:
    raw_text = """
    Vendor: ACME
    PO Number: PO-1007
    Purchase Order Date: 25/07/2026
    Total Amount: 500.00
    """

    data = PurchaseOrderExtractor().extract(raw_text)

    assert data["currency"] is None
    assert data["subtotal"] is None
    assert data["tax"] is None
    assert data["gst"] is None
    assert data["confidence"] == 0.5
