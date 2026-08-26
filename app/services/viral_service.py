"""Viral Idea Finder orchestration service.

Collects content from source adapters, normalizes it, clusters related
items, scores each cluster, and generates viral idea objects.  This is
the main entry point for the viral pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.db.models.viral import ViralContentItem, ViralIdea
from app.repositories.viral_repository import ViralRepository
from app.schemas.viral import (
    ScanRequest,
    ScanResponse,
    ViralContentItemResponse,
    ViralIdeaResponse,
)
from app.viral.adapters import get_adapter, list_sources
from app.viral.clustering import cluster_items
from app.viral.ideas import (
    generate_content_angles,
    generate_summary,
    generate_title,
    generate_topic,
    generate_why_it_matters,
)
from app.viral.scoring import compute_viral_score

logger = logging.getLogger(__name__)


class ViralService:
    """Orchestrate the viral idea discovery pipeline."""

    def __init__(self, repository: ViralRepository):
        self.repository = repository

    async def scan(self, request: ScanRequest) -> ScanResponse:
        """Run a full scan: collect, normalize, cluster, score, generate ideas."""
        sources_used: list[str] = []
        all_items: list[ViralContentItem] = []

        target_sources = request.sources or list_sources()

        for source_name in target_sources:
            try:
                adapter = get_adapter(source_name)
                normalized = await adapter.search(
                    request.query, max_items=request.max_items_per_source
                )
                for item in normalized:
                    db_item = ViralContentItem(
                        source=item.source,
                        source_url=item.source_url,
                        title=item.title,
                        description=item.description,
                        author=item.author,
                        published_at=item.published_at,
                        topic=item.topic,
                        language=item.language,
                        engagement=item.engagement or {},
                        metadata_json=item.metadata or {},
                    )
                    all_items.append(db_item)

                if normalized:
                    sources_used.append(source_name)
            except Exception:
                logger.warning(
                    "Source %s failed during scan", source_name, exc_info=True
                )

        # Persist collected items
        if all_items:
            self.repository.save_content_items(all_items)

        # Cluster and generate ideas
        ideas = self._cluster_and_generate(all_items)

        return ScanResponse(
            items_collected=len(all_items),
            ideas_generated=len(ideas),
            sources_used=sources_used,
            message=f"Collected {len(all_items)} items from {len(sources_used)} sources, "
            f"generated {len(ideas)} viral ideas",
        )

    def _cluster_and_generate(self, items: list[ViralContentItem]) -> list[ViralIdea]:
        """Cluster content items and generate viral ideas."""
        if not items:
            return []

        # Convert to dicts for clustering
        item_dicts: list[dict[str, Any]] = [
            {
                "id": item.id,
                "source": item.source,
                "title": item.title,
                "description": item.description,
                "engagement": item.engagement or {},
                "published_at": item.published_at,
                "topic": item.topic,
            }
            for item in items
        ]

        clusters = cluster_items(item_dicts)
        ideas: list[ViralIdea] = []

        for cluster_indices in clusters:
            cluster_items_list = [item_dicts[i] for i in cluster_indices]

            # Extract cluster properties
            topic = generate_topic(cluster_items_list)
            title = generate_title(cluster_items_list)
            summary = generate_summary(cluster_items_list, topic)

            # Gather scores
            platforms = sorted({it["source"] for it in cluster_items_list})
            all_engagement = [it.get("engagement", {}) for it in cluster_items_list]
            all_dates = [it.get("published_at") for it in cluster_items_list]

            # Use the first item's engagement for the main score
            main_engagement = cluster_items_list[0].get("engagement", {})
            main_date = cluster_items_list[0].get("published_at")

            scores = compute_viral_score(
                engagement=main_engagement,
                published_at=main_date,
                source_count=len(platforms),
                item_count=len(cluster_items_list),
                engagement_list=all_engagement,
                published_dates=all_dates,
            )

            why_it_matters = generate_why_it_matters(cluster_items_list, scores)
            angles = generate_content_angles(cluster_items_list, topic)

            idea = ViralIdea(
                title=title,
                summary=summary,
                topic=topic,
                source_platforms=platforms,
                source_item_ids=[it["id"] for it in cluster_items_list],
                viral_score=scores["viral_score"],
                novelty_score=scores["novelty_score"],
                momentum_score=scores["momentum_score"],
                cross_source_score=scores["cross_source_score"],
                engagement_score=scores["engagement_score"],
                evidence=scores["evidence"],
                why_it_matters=why_it_matters,
                suggested_angles=angles,
            )
            ideas.append(idea)

        # Persist ideas
        if ideas:
            self.repository.save_ideas(ideas)

        return ideas

    def list_ideas(
        self,
        query: str | None = None,
        source: str | None = None,
        topic: str | None = None,
        min_score: float = 0.0,
        limit: int = 50,
    ) -> list[ViralIdeaResponse]:
        """List scored viral ideas with optional filters."""
        # ``query`` acts as a topic filter when no explicit topic is set
        effective_topic = topic or query
        ideas = self.repository.list_ideas(
            topic=effective_topic, source=source, min_score=min_score, limit=limit
        )
        return [ViralIdeaResponse.model_validate(idea) for idea in ideas]

    def list_content_items(
        self,
        source: str | None = None,
        topic: str | None = None,
        limit: int = 100,
    ) -> list[ViralContentItemResponse]:
        """List collected content items."""
        items = self.repository.get_content_items(
            source=source, topic=topic, limit=limit
        )
        return [ViralContentItemResponse.model_validate(item) for item in items]

    def get_idea(self, idea_id: str) -> ViralIdeaResponse | None:
        """Get a single viral idea by ID."""
        idea = self.repository.get_idea(idea_id)
        if idea is None:
            return None
        return ViralIdeaResponse.model_validate(idea)
