"""Knowledge Ingestion Engine orchestration."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from app.kie.classifiers.document_classifier import DocumentClassifier
from app.kie.extractors import (
    BankStatementExtractor,
    InvoiceExtractor,
    PurchaseOrderExtractor,
    ReceiptExtractor,
)
from app.kie.models import DocumentMetadata, DocumentResult, DocumentType
from app.kie.ocr.router import OCRRouter
from app.kie.parsers import EmailParser, ExcelParser, ImageParser, PDFParser
from app.kie.registry import ExtractorRegistry, ParserRegistry


class KnowledgeEngine:
    """Coordinate parsing, classification, and optional extraction for a file."""

    def __init__(
        self,
        parser_registry: ParserRegistry | None = None,
        extractor_registry: ExtractorRegistry | None = None,
        classifier: DocumentClassifier | None = None,
        ocr_router: OCRRouter | None = None,
    ) -> None:
        self.parser_registry = parser_registry or self._default_parser_registry()
        self.extractor_registry = extractor_registry or self._default_extractor_registry()
        self.classifier = classifier or DocumentClassifier()
        self.ocr_router = ocr_router or OCRRouter()

    def process(self, file_path: str | Path) -> DocumentResult:
        """Process one local file through the KIE pipeline.

        Current parsers and extractors deliberately provide deterministic
        placeholders. Their contracts are ready for real implementations.
        """

        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Document does not exist: {path}")

        metadata = self._metadata_for(path)
        document_type = self.classifier.classify(path)
        parser = self.parser_registry.get_parser(str(path))
        raw_text = parser.parse(path) if parser else ""
        if document_type is DocumentType.IMAGE:
            raw_text = self.ocr_router.extract_text(path).text
        extractor = self.extractor_registry.get_extractor(document_type)
        structured_data = extractor.extract(raw_text) if extractor else {}

        return DocumentResult(
            document_type=document_type,
            metadata=metadata,
            raw_text=raw_text,
            structured_data=structured_data,
            confidence=1.0 if document_type is not DocumentType.UNKNOWN else 0.0,
            parser=getattr(parser, "name", None),
            extractor=getattr(extractor, "name", None),
        )

    @staticmethod
    def _metadata_for(path: Path) -> DocumentMetadata:
        mime_type, _ = mimetypes.guess_type(path.name)
        return DocumentMetadata(
            filename=path.name,
            extension=path.suffix.lower(),
            size=path.stat().st_size,
            mime_type=mime_type or "application/octet-stream",
        )

    @staticmethod
    def _default_parser_registry() -> ParserRegistry:
        registry = ParserRegistry()
        for parser in (PDFParser(), ImageParser(), ExcelParser(), EmailParser()):
            registry.register(parser)
        return registry

    @staticmethod
    def _default_extractor_registry() -> ExtractorRegistry:
        registry = ExtractorRegistry()
        registry.register(DocumentType.INVOICE, InvoiceExtractor())
        registry.register(DocumentType.RECEIPT, ReceiptExtractor())
        registry.register(DocumentType.BANK_STATEMENT, BankStatementExtractor())
        registry.register(DocumentType.PURCHASE_ORDER, PurchaseOrderExtractor())
        return registry
