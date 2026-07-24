"""Knowledge Ingestion Engine orchestration."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from app.kie.classifiers.content_classifier import ContentClassifier
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
    """Coordinate parsing, OCR, classification, and extraction."""

    def __init__(
        self,
        parser_registry: ParserRegistry | None = None,
        extractor_registry: ExtractorRegistry | None = None,
        classifier: DocumentClassifier | None = None,
        content_classifier: ContentClassifier | None = None,
        ocr_router: OCRRouter | None = None,
    ) -> None:
        self.parser_registry = parser_registry or self._default_parser_registry()
        self.extractor_registry = extractor_registry or self._default_extractor_registry()
        self.classifier = classifier or DocumentClassifier()
        self.content_classifier = content_classifier or ContentClassifier()
        self.ocr_router = ocr_router or OCRRouter()

    def process(self, file_path: str | Path) -> DocumentResult:
        """Process one local file through the complete KIE pipeline."""

        path = Path(file_path)

        if not path.is_file():
            raise FileNotFoundError(f"Document does not exist: {path}")

        metadata = self._metadata_for(path)

        # Stage 1: identify the physical/container format.
        container_type = self.classifier.classify(path)

        # Stage 2: parse the document into text.
        parser = self.parser_registry.get_parser(str(path))
        raw_text = parser.parse(path) if parser else ""

        # Images require OCR to obtain readable text.
        if container_type is DocumentType.IMAGE:
            raw_text = self.ocr_router.extract_text(path).text

        # Stage 3: determine the business meaning of the document.
        business_type = self.content_classifier.classify(raw_text)

        # Stage 4: use the business-specific extractor when recognized.
        extractor = self.extractor_registry.get_extractor(business_type)
        structured_data = extractor.extract(raw_text) if extractor else {}

        # Preserve existing behaviour when business content is unknown.
        result_type = (
            business_type
            if business_type is not DocumentType.UNKNOWN
            else container_type
        )

        return DocumentResult(
            document_type=result_type,
            metadata=metadata,
            raw_text=raw_text,
            structured_data=structured_data,
            confidence=1.0 if result_type is not DocumentType.UNKNOWN else 0.0,
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

        for parser in (
            PDFParser(),
            ImageParser(),
            ExcelParser(),
            EmailParser(),
        ):
            registry.register(parser)

        return registry

    @staticmethod
    def _default_extractor_registry() -> ExtractorRegistry:
        registry = ExtractorRegistry()

        registry.register(DocumentType.INVOICE, InvoiceExtractor())
        registry.register(DocumentType.RECEIPT, ReceiptExtractor())
        registry.register(
            DocumentType.BANK_STATEMENT,
            BankStatementExtractor(),
        )
        registry.register(
            DocumentType.PURCHASE_ORDER,
            PurchaseOrderExtractor(),
        )

        return registry