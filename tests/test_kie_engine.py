"""Tests for the Knowledge Ingestion Engine foundation."""

from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.kie.classifiers.document_classifier import DocumentClassifier
from app.kie.engine import KnowledgeEngine
from app.kie.extractors.invoice_extractor import InvoiceExtractor
from app.kie.models import DocumentResult, DocumentType
from app.kie.parsers.base_parser import BaseParser
from app.kie.parsers.pdf_parser import PDFParser
from app.kie.registry import ExtractorRegistry, ParserRegistry
from app.kie.service import KnowledgeService


class FakeInvoiceParser(BaseParser):
    """Return predictable invoice text for KIE integration tests."""

    name = "fake_invoice_parser"
    supported_extensions = (".txt",)

    def __init__(self, text: str) -> None:
        self.text = text

    def supports(self, file_path: str | Path) -> bool:
        return Path(file_path).suffix.lower() in self.supported_extensions

    def parse(self, file_path: str | Path) -> str:
        return self.text


def make_invoice_engine(raw_text: str) -> KnowledgeEngine:
    """Create a KnowledgeEngine with predictable invoice input."""

    parser_registry = ParserRegistry()
    parser_registry.register(FakeInvoiceParser(raw_text))

    return KnowledgeEngine(
        parser_registry=parser_registry,
    )


def test_engine_registers_default_parsers_and_extractors() -> None:
    engine = KnowledgeEngine()

    assert isinstance(
        engine.parser_registry.get_parser("document.pdf"),
        PDFParser,
    )
    assert isinstance(
        engine.extractor_registry.get_extractor(DocumentType.INVOICE),
        InvoiceExtractor,
    )


@pytest.mark.parametrize(
    ("filename", "document_type"),
    [
        ("file.pdf", DocumentType.PDF),
        ("file.xlsx", DocumentType.EXCEL),
        ("file.jpg", DocumentType.IMAGE),
        ("file.eml", DocumentType.EMAIL),
        ("file.bin", DocumentType.UNKNOWN),
    ],
)
def test_classifier_uses_extensions(
    filename: str,
    document_type: DocumentType,
) -> None:
    assert DocumentClassifier().classify(filename) is document_type


def test_registries_register_and_return_components() -> None:
    parser_registry = ParserRegistry()
    parser = PDFParser()

    parser_registry.register(parser)

    assert parser_registry.get_parser("budget.pdf") is parser

    extractor_registry = ExtractorRegistry()
    extractor = InvoiceExtractor()

    extractor_registry.register(DocumentType.INVOICE, extractor)

    assert extractor_registry.get_extractor(DocumentType.INVOICE) is extractor


def test_parser_registry_supports_typed_registration() -> None:
    registry = ParserRegistry()
    parser = PDFParser()

    registry.register(DocumentType.INVOICE, parser)

    assert registry.get_parser(DocumentType.INVOICE) is parser


def test_invoice_extractor_returns_structured_invoice() -> None:
    raw_text = """
    ACME SUPPLIES PRIVATE LIMITED
    Invoice Number: INV-1001
    Invoice Date: 24/07/2026
    Currency: INR
    Subtotal: 1000.00
    GST: 180.00
    Grand Total: 1180.00
    """

    data = InvoiceExtractor().extract(raw_text)

    assert data["document_kind"] == "invoice"
    assert data["vendor"] == "ACME SUPPLIES PRIVATE LIMITED"
    assert data["invoice_number"] == "INV-1001"
    assert data["invoice_date"] == "24/07/2026"
    assert data["currency"] == "INR"
    assert data["subtotal"] == 1000.00
    assert data["gst"] == 180.00
    assert data["grand_total"] == 1180.00
    assert "confidence" in data


def test_engine_generates_document_result(tmp_path: Path) -> None:
    document = tmp_path / "statement.pdf"

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)

    with document.open("wb") as pdf_file:
        writer.write(pdf_file)

    result = KnowledgeEngine().process(document)

    assert isinstance(result, DocumentResult)
    assert result.document_type is DocumentType.PDF
    assert result.metadata.filename == "statement.pdf"
    assert result.metadata.extension == ".pdf"
    assert result.parser == "pdf_parser"
    assert isinstance(result.raw_text, str)
    assert result.structured_data == {}


def test_service_delegates_to_engine(tmp_path: Path) -> None:
    document = tmp_path / "mail.eml"
    document.write_text("From: user@example.com")

    result = KnowledgeService().process(document)

    assert result.document_type is DocumentType.EMAIL
    assert result.parser == "email_parser"


def test_engine_validates_valid_invoice(tmp_path: Path) -> None:
    raw_text = """
    ACME SUPPLIES PRIVATE LIMITED
    Tax Invoice
    Invoice Number: INV-2001
    Invoice Date: 25/07/2026
    Currency: INR
    Subtotal: 1000.00
    GST: 180.00
    Grand Total: 1180.00
    """

    document = tmp_path / "invoice.txt"
    document.write_text(raw_text)

    result = make_invoice_engine(raw_text).process(document)

    assert result.document_type is DocumentType.INVOICE
    assert result.extractor == "invoice_extractor"

    validation = result.structured_data["validation"]

    assert validation["status"] == "valid"
    assert validation["is_valid"] is True
    assert validation["issues"] == []
    assert validation["warnings"] == []


def test_engine_flags_invoice_with_incorrect_total(
    tmp_path: Path,
) -> None:
    raw_text = """
    ACME SUPPLIES PRIVATE LIMITED
    Tax Invoice
    Invoice Number: INV-2002
    Invoice Date: 25/07/2026
    Currency: INR
    Subtotal: 1000.00
    GST: 180.00
    Grand Total: 1500.00
    """

    document = tmp_path / "invoice.txt"
    document.write_text(raw_text)

    result = make_invoice_engine(raw_text).process(document)

    validation = result.structured_data["validation"]

    assert validation["status"] == "invalid"
    assert validation["is_valid"] is False
    assert (
        "Invoice total does not match subtotal plus tax."
        in validation["issues"]
    )


def test_engine_flags_invoice_missing_required_data(
    tmp_path: Path,
) -> None:
    raw_text = """
    Tax Invoice
    Invoice Number: INV-2003
    Currency: INR
    Subtotal: 1000.00
    GST: 180.00
    Grand Total: 1180.00
    """

    document = tmp_path / "invoice.txt"
    document.write_text(raw_text)

    result = make_invoice_engine(raw_text).process(document)

    validation = result.structured_data["validation"]

    assert validation["status"] == "invalid"
    assert validation["is_valid"] is False
    assert any(
        "invoice_date" in issue
        for issue in validation["issues"]
    )