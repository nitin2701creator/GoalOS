"""Repository for Viral Idea Finder persistence."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import String, desc, func, select
from sqlalchemy.orm import Session

from app.db.models.viral import ViralContentItem, ViralIdea


class ViralRepository:
    """Database access for viral content items and ideas."""

    def __init__(self, db: Session):
        self.db = db

    # -- Content Items --

    def save_content_items(self, items: list[ViralContentItem]) -> list[ViralContentItem]:
        """Bulk-save normalized content items."""
        self.db.add_all(items)
        self.db.commit()
        for item in items:
            self.db.refresh(item)
        return items

    def get_content_items(
        self,
        source: str | None = None,
        topic: str | None = None,
        limit: int = 100,
    ) -> Sequence[ViralContentItem]:
        """Query content items with optional filters."""
        stmt = select(ViralContentItem).order_by(desc(ViralContentItem.collected_at))
        if source:
            stmt = stmt.where(ViralContentItem.source == source)
        if topic:
            stmt = stmt.where(ViralContentItem.topic.ilike(f"%{topic}%"))
        return self.db.scalars(stmt.limit(limit)).all()

    def content_item_count(self) -> int:
        return self.db.scalar(select(func.count(ViralContentItem.id)))

    # -- Viral Ideas --

    def save_idea(self, idea: ViralIdea) -> ViralIdea:
        self.db.add(idea)
        self.db.commit()
        self.db.refresh(idea)
        return idea

    def save_ideas(self, ideas: list[ViralIdea]) -> list[ViralIdea]:
        self.db.add_all(ideas)
        self.db.commit()
        for idea in ideas:
            self.db.refresh(idea)
        return ideas

    def list_ideas(
        self,
        topic: str | None = None,
        source: str | None = None,
        min_score: float = 0.0,
        limit: int = 50,
    ) -> Sequence[ViralIdea]:
        """List viral ideas ordered by score, with optional filters."""
        stmt = select(ViralIdea).where(ViralIdea.viral_score >= min_score)
        if topic:
            stmt = stmt.where(ViralIdea.topic.ilike(f"%{topic}%"))
        if source:
            # Filter by JSON array contains
            stmt = stmt.where(
                ViralIdea.source_platforms.cast(String).contains(f'"{source}"')
            )
        stmt = stmt.order_by(desc(ViralIdea.viral_score))
        return self.db.scalars(stmt.limit(limit)).all()

    def get_idea(self, idea_id: str) -> ViralIdea | None:
        return self.db.get(ViralIdea, idea_id)

    def delete_all(self) -> None:
        """Clear all viral data (for testing or refresh)."""
        self.db.query(ViralIdea).delete()
        self.db.query(ViralContentItem).delete()
        self.db.commit()
