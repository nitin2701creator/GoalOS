"""Registries for replacing KIE pipeline components."""

from __future__ import annotations

from typing import Any

from app.kie.models import DocumentType
from app.kie.parsers.base_parser import BaseParser


class ParserRegistry:
    """Store parser instances and select the first one supporting a path."""

    def __init__(self) -> None:
        self._parsers: dict[str, BaseParser] = {}
        self._typed_parsers: dict[DocumentType, BaseParser] = {}

    def register(
        self,
        parser_or_type: BaseParser | DocumentType,
        parser: BaseParser | None = None,
        name: str | None = None,
    ) -> None:
        """Register a parser globally or under a specific document type.

        Typed registration is useful for custom classifiers; regular
        registration lets built-in parsers advertise their own extensions.
        """

        document_type = parser_or_type if isinstance(parser_or_type, DocumentType) else None
        resolved_parser = parser if document_type is not None else parser_or_type
        if document_type is not None and parser is None:
            raise TypeError("parser is required when registering a document type")
        if not isinstance(resolved_parser, BaseParser):
            raise TypeError("parser must inherit BaseParser")
        if document_type is not None:
            if document_type in self._typed_parsers:
                raise ValueError(f"Parser already registered: {document_type.value}")
            self._typed_parsers[document_type] = resolved_parser
            return
        key = name or getattr(resolved_parser, "name", resolved_parser.__class__.__name__)
        if key in self._parsers:
            raise ValueError(f"Parser already registered: {key}")
        self._parsers[key] = resolved_parser

    def get_parser(self, file_path: str | DocumentType) -> BaseParser | None:
        if isinstance(file_path, DocumentType):
            return self._typed_parsers.get(file_path)
        return next((parser for parser in self._parsers.values() if parser.supports(file_path)), None)


class ExtractorRegistry:
    """Map document types to structured-data extractors."""

    def __init__(self) -> None:
        self._extractors: dict[DocumentType, Any] = {}

    def register(self, document_type: DocumentType, extractor: Any) -> None:
        if not isinstance(document_type, DocumentType):
            raise TypeError("document_type must be a DocumentType")
        if not callable(getattr(extractor, "extract", None)):
            raise TypeError("extractor must expose extract()")
        if document_type in self._extractors:
            raise ValueError(f"Extractor already registered: {document_type.value}")
        self._extractors[document_type] = extractor

    def get_extractor(self, document_type: DocumentType) -> Any | None:
        return self._extractors.get(document_type)
