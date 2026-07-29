"""Tests for business document content classification."""

import pytest

from app.kie.classifiers.content_classifier import ContentClassifier
from app.kie.models import DocumentType


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("TAX INVOICE\nInvoice Number: INV-1001", DocumentType.INVOICE),
        ("Invoice No: 5001\nAmount Due: 2500", DocumentType.INVOICE),
        ("PAYMENT RECEIVED\nReceipt 1234", DocumentType.RECEIPT),
        (
            "BANK STATEMENT\nOpening Balance: 1000\nClosing Balance: 2000",
            DocumentType.BANK_STATEMENT,
        ),
        ("PURCHASE ORDER\nPO Number: PO-100", DocumentType.PURCHASE_ORDER),
    ],
)
def test_classifier_detects_business_document_type(
    raw_text: str,
    expected: DocumentType,
) -> None:
    classifier = ContentClassifier()

    assert classifier.classify(raw_text) is expected


def test_classifier_returns_unknown_for_unrecognized_text() -> None:
    classifier = ContentClassifier()

    assert classifier.classify("General business document") is DocumentType.UNKNOWN


def test_classifier_is_case_insensitive() -> None:
    classifier = ContentClassifier()

    assert classifier.classify("tax invoice") is DocumentType.INVOICE
    assert classifier.classify("TAX INVOICE") is DocumentType.INVOICE