"""Application-facing facade for knowledge ingestion."""

from __future__ import annotations

from pathlib import Path

from app.kie.engine import KnowledgeEngine
from app.kie.models import DocumentResult


class KnowledgeService:
    """Expose knowledge ingestion without leaking pipeline composition details."""

    def __init__(self, engine: KnowledgeEngine | None = None) -> None:
        self.engine = engine or KnowledgeEngine()

    def process(self, file_path: str | Path) -> DocumentResult:
        """Ingest one document through the configured engine."""

        return self.engine.process(file_path)
