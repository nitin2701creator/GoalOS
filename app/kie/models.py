"""Data contracts for the Knowledge Ingestion Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DocumentType(str, Enum):
    """Document categories understood by the ingestion engine."""

    UNKNOWN = "unknown"
    PDF = "pdf"
    IMAGE = "image"
    EXCEL = "excel"
    EMAIL = "email"
    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"
    PURCHASE_ORDER = "purchase_order"
    RECEIPT = "receipt"


@dataclass(frozen=True)
class DocumentMetadata:
    """File attributes collected before parsing a document."""

    filename: str
    extension: str
    size: int
    mime_type: str


@dataclass
class DocumentResult:
    """The normalized output of a KIE processing run."""

    document_type: DocumentType
    metadata: DocumentMetadata
    raw_text: str
    structured_data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    parser: str | None = None
    extractor: str | None = None
