"""Tests for the Viral Idea Finder.

Covers normalization, scoring, clustering, idea generation, repository
persistence, and API response validation.  All external APIs are mocked
— no real network calls are made.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.viral import ViralContentItem, ViralIdea
from app.repositories.viral_repository import ViralRepository
from app.schemas.viral import (
    ScanRequest,
    ScanResponse,
    ViralContentItemResponse,
    ViralIdeaResponse,
)
from app.viral.adapters.base import NormalizedItem
from app.viral.adapters.rss import RSSAdapter
from app.viral.clustering import (
    cluster_items,
    compute_content_similarity,
    compute_title_similarity,
    jaccard_similarity,
)
from app.viral.ideas import (
    generate_content_angles,
    generate_summary,
    generate_title,
    generate_topic,
    generate_why_it_matters,
)
from app.viral.scoring import (
    compute_viral_score,
    score_cross_source,
    score_engagement,
    score_momentum,
    score_novelty,
    score_recency,
)

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite database for tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def repo(db_session: Session):
    return ViralRepository(db_session)


def _make_item(
    source: str = "rss",
    title: str = "Test Article",
    description: str = "A test article about testing",
    engagement: dict | None = None,
    **kwargs,
) -> ViralContentItem:
    return ViralContentItem(
        source=source,
        source_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        title=title,
        description=description,
        engagement=engagement or {},
        **kwargs,
    )


def _make_normalized(
    source: str = "rss",
    title: str = "Test Article",
    description: str = "Test description",
    **kwargs,
) -> NormalizedItem:
    return NormalizedItem(
        source=source,
        source_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        title=title,
        description=description,
        **kwargs,
    )


# ── Scoring Tests ───────────────────────────────────────────────────


class TestScoring:
    def test_engagement_no_metrics(self):
        score, evidence = score_engagement({})
        assert score == 0.0
        assert "No engagement" in evidence

    def test_engagement_with_points(self):
        score, evidence = score_engagement({"points": 100})
        assert 0.0 < score <= 1.0
        assert "100" in evidence

    def test_engagement_nested_dict(self):
        score, _ = score_engagement({"likes": {"total": 500}})
        assert 0.0 < score <= 1.0

    def test_engagement_all_zero(self):
        score, evidence = score_engagement({"points": 0, "comments": 0})
        assert score == 0.0
        assert "zero" in evidence

    def test_recency_no_date(self):
        score, evidence = score_recency(None)
        assert score == 0.5
        assert "No publication date" in evidence

    def test_recency_very_recent(self):
        now = datetime.now(timezone.utc)
        score, _ = score_recency(now)
        assert score == 1.0

    def test_recency_one_day_old(self):
        now = datetime.now(timezone.utc)
        from datetime import timedelta

        one_day = now - timedelta(hours=24)
        score, _ = score_recency(one_day, now=now)
        assert 0.8 <= score <= 1.0

    def test_recency_one_week_old(self):
        now = datetime.now(timezone.utc)
        from datetime import timedelta

        one_week = now - timedelta(days=7)
        score, _ = score_recency(one_week, now=now)
        assert score < 0.5

    def test_cross_source_single(self):
        score, evidence = score_cross_source(1)
        assert score == 0.1
        assert "Single source" in evidence

    def test_cross_source_two(self):
        score, _ = score_cross_source(2)
        assert score == 0.5

    def test_cross_source_many(self):
        score, _ = score_cross_source(5)
        assert score >= 0.9

    def test_novelty_few_items(self):
        score, _ = score_novelty(1, None)
        assert score == 1.0

    def test_novelty_many_items(self):
        score, _ = score_novelty(15, None)
        assert score == 0.2

    def test_momentum_no_data(self):
        score, evidence = score_momentum([], [])
        assert 0.0 < score < 1.0
        assert "Insufficient" in evidence

    def test_momentum_all_engaged(self):
        engagements = [{"likes": 10}, {"likes": 20}, {"likes": 30}]
        score, evidence = score_momentum(engagements, [])
        assert score >= 0.5
        assert "3/3" in evidence

    def test_compute_viral_score_full(self):
        now = datetime.now(timezone.utc)
        scores = compute_viral_score(
            engagement={"points": 50},
            published_at=now,
            source_count=3,
            item_count=5,
            engagement_list=[{"points": 50}, {"likes": 20}, {"retweets": 10}],
            published_dates=[now, now, now],
            now=now,
        )
        assert 0.0 <= scores["viral_score"] <= 1.0
        assert 0.0 <= scores["engagement_score"] <= 1.0
        assert 0.0 <= scores["momentum_score"] <= 1.0
        assert 0.0 <= scores["cross_source_score"] <= 1.0
        assert 0.0 <= scores["novelty_score"] <= 1.0
        assert len(scores["evidence"]) == 5

    def test_compute_viral_score_minimal(self):
        scores = compute_viral_score(
            engagement={},
            published_at=None,
            source_count=1,
            item_count=1,
        )
        assert 0.0 <= scores["viral_score"] <= 1.0


# ── Clustering Tests ────────────────────────────────────────────────


class TestClustering:
    def test_empty_items(self):
        assert cluster_items([]) == []

    def test_single_item(self):
        items = [{"title": "AI breakthrough", "description": "Major news"}]
        clusters = cluster_items(items)
        assert len(clusters) == 1
        assert clusters[0] == [0]

    def test_identical_titles_cluster_together(self):
        items = [
            {"title": "OpenAI releases GPT-5", "description": "The new model is here"},
            {"title": "OpenAI releases GPT-5", "description": "Latest AI model launch"},
        ]
        clusters = cluster_items(items)
        assert len(clusters) == 1

    def test_different_topics_separate(self):
        items = [
            {"title": "OpenAI releases GPT-5", "description": "Latest AI model launch"},
            {"title": "New recipe for chocolate cake", "description": "Delicious dessert ideas"},
        ]
        clusters = cluster_items(items)
        assert len(clusters) == 2

    def test_similar_content_groups_together(self):
        items = [
            {"title": "Something", "description": "AI model released today by OpenAI corporation"},
            {"title": "Another", "description": "AI model released today by Google corporation"},
        ]
        clusters = cluster_items(items, content_threshold=0.25)
        assert len(clusters) == 1

    def test_jaccard_similarity(self):
        assert jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"}) == 1.0
        assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0
        assert 0.0 < jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"}) < 1.0

    def test_title_similarity(self):
        sim = compute_title_similarity(
            "OpenAI launches new model",
            "OpenAI launches new AI model",
        )
        assert sim > 0.4

    def test_title_similarity_different(self):
        sim = compute_title_similarity(
            "OpenAI launches new model",
            "Best chocolate cake recipe",
        )
        assert sim == 0.0


# ── Idea Generation Tests ───────────────────────────────────────────


class TestIdeaGeneration:
    def test_generate_title(self):
        items = [
            {"title": "AI Model Breaks Records"},
            {"title": "New AI Model Released"},
        ]
        title = generate_title(items)
        assert "Trending" in title
        assert len(title) > 10

    def test_generate_title_empty(self):
        title = generate_title([])
        assert "Unknown Trend" in title

    def test_generate_summary(self):
        items = [
            {"source": "rss", "title": "Article 1"},
            {"source": "jina", "title": "Article 2"},
        ]
        summary = generate_summary(items, "AI")
        assert "2 content items" in summary
        assert "jina" in summary

    def test_generate_topic(self):
        items = [
            {"title": "Machine Learning in Healthcare"},
            {"title": "ML Advances in Medicine"},
        ]
        topic = generate_topic(items)
        assert len(topic) > 0

    def test_generate_why_it_matters(self):
        items = [{"source": "rss"}, {"source": "jina"}, {"source": "rss"}]
        scores = {
            "viral_score": 0.8,
            "cross_source_score": 0.8,
            "momentum_score": 0.6,
        }
        reason = generate_why_it_matters(items, scores)
        assert len(reason) > 20
        assert "multiple platforms" in reason

    def test_generate_content_angles(self):
        items = [{"title": "Test"}]
        angles = generate_content_angles(items, "AI")
        assert len(angles) >= 4
        assert any("educational" in a.lower() or "explain" in a.lower() for a in angles)
        assert any("contrarian" in a.lower() for a in angles)
        assert any("video" in a.lower() for a in angles)


# ── Repository Tests ────────────────────────────────────────────────


class TestRepository:
    def test_save_and_retrieve_content_item(self, repo: ViralRepository):
        item = _make_item(title="Test Persistence")
        saved = repo.save_content_items([item])
        assert len(saved) == 1
        assert saved[0].title == "Test Persistence"

    def test_get_content_items_by_source(self, repo: ViralRepository):
        repo.save_content_items([
            _make_item(source="rss", title="RSS Item"),
            _make_item(source="jina", title="Jina Item"),
        ])
        rss_items = repo.get_content_items(source="rss")
        assert len(rss_items) == 1
        assert rss_items[0].source == "rss"

    def test_save_and_retrieve_idea(self, repo: ViralRepository):
        idea = ViralIdea(
            title="Test Idea",
            summary="A test idea",
            viral_score=0.75,
            why_it_matters="Testing",
        )
        saved = repo.save_idea(idea)
        assert saved.id is not None
        assert saved.viral_score == 0.75

    def test_list_ideas_min_score(self, repo: ViralRepository):
        repo.save_ideas([
            ViralIdea(title="High", summary="", viral_score=0.9, why_it_matters=""),
            ViralIdea(title="Low", summary="", viral_score=0.1, why_it_matters=""),
        ])
        high_only = repo.list_ideas(min_score=0.5)
        assert len(high_only) == 1
        assert high_only[0].title == "High"

    def test_delete_all(self, repo: ViralRepository):
        repo.save_content_items([_make_item()])
        repo.save_ideas([ViralIdea(title="X", summary="", viral_score=0.5, why_it_matters="")])
        repo.delete_all()
        assert len(repo.get_content_items()) == 0

    def test_content_item_count(self, repo: ViralRepository):
        assert repo.content_item_count() == 0
        repo.save_content_items([_make_item(), _make_item(title="Two")])
        assert repo.content_item_count() == 2


# ── Schema Tests ────────────────────────────────────────────────────


class TestSchemas:
    def test_viral_idea_response(self):
        response = ViralIdeaResponse(
            id="test-id",
            title="Test",
            summary="Summary",
            viral_score=0.75,
            novelty_score=0.8,
            momentum_score=0.6,
            cross_source_score=0.9,
            engagement_score=0.5,
            why_it_matters="Because",
            created_at=datetime.now(timezone.utc),
        )
        assert response.viral_score == 0.75

    def test_scan_request(self):
        req = ScanRequest(query="AI trends", sources=["rss"], max_items_per_source=10)
        assert req.query == "AI trends"
        assert req.sources == ["rss"]

    def test_scan_response(self):
        resp = ScanResponse(
            items_collected=25,
            ideas_generated=5,
            sources_used=["rss", "jina"],
            message="Done",
        )
        assert resp.items_collected == 25


# ── RSS Adapter Tests ───────────────────────────────────────────────


class TestRSSAdapter:
    def test_parse_rss_feed(self):
        adapter = RSSAdapter()
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
        <channel>
            <title>Test Feed</title>
            <item>
                <title>Test Article</title>
                <link>https://example.com/test</link>
                <description>A test article about AI</description>
                <author>Test Author</author>
                <pubDate>Mon, 25 Aug 2025 10:00:00 +0000</pubDate>
            </item>
            <item>
                <title>Another Article</title>
                <link>https://example.com/another</link>
                <description>More content here</description>
            </item>
        </channel>
        </rss>"""
        items = adapter._parse_feed(rss_xml, source_tag="rss:test")
        assert len(items) == 2
        assert items[0].title == "Test Article"
        assert items[0].author == "Test Author"
        assert items[0].source == "rss:test"

    def test_parse_atom_feed(self):
        adapter = RSSAdapter()
        atom_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <title>Atom Entry</title>
                <link rel="alternate" href="https://example.com/atom"/>
                <summary>Atom summary text</summary>
                <author><name>Atom Author</name></author>
                <published>2025-08-25T10:00:00Z</published>
            </entry>
        </feed>"""
        items = adapter._parse_feed(atom_xml, source_tag="rss:test")
        assert len(items) == 1
        assert items[0].title == "Atom Entry"
        assert items[0].author == "Atom Author"

    def test_parse_invalid_xml(self):
        adapter = RSSAdapter()
        items = adapter._parse_feed("not xml at all")
        assert items == []

    def test_parse_empty_feed(self):
        adapter = RSSAdapter()
        items = adapter._parse_feed("<rss><channel></channel></rss>")
        assert items == []


# ── Adapter Registry Tests ──────────────────────────────────────────


class TestAdapterRegistry:
    def test_list_sources(self):
        from app.viral.adapters import list_sources
        sources = list_sources()
        assert "rss" in sources
        assert "jina" in sources

    def test_get_adapter(self):
        from app.viral.adapters import get_adapter
        adapter = get_adapter("rss")
        assert adapter.source_name == "rss"

    def test_get_unknown_adapter(self):
        from app.viral.adapters import get_adapter
        with pytest.raises(ValueError, match="Unknown source"):
            get_adapter("nonexistent")


# ── Service Integration Tests ───────────────────────────────────────


class TestViralService:
    @pytest.mark.asyncio
    async def test_scan_with_mocked_adapters(self, repo: ViralRepository):
        from app.services.viral_service import ViralService

        service = ViralService(repo)

        mock_items = [
            _make_normalized(source="rss", title="AI Breakthrough Today"),
            _make_normalized(source="rss", title="AI Makes Huge Progress"),
        ]

        with patch("app.services.viral_service.get_adapter") as mock_get:
            mock_adapter = AsyncMock()
            mock_adapter.search.return_value = mock_items
            mock_get.return_value = mock_adapter

            request = ScanRequest(
                query="AI", sources=["rss"], max_items_per_source=10
            )
            result = await service.scan(request)

            assert result.items_collected == 2
            assert result.sources_used == ["rss"]
            assert isinstance(result.ideas_generated, int)

    def test_list_ideas_query_filter(self, repo: ViralRepository):
        from app.services.viral_service import ViralService

        repo.save_ideas([
            ViralIdea(title="AI Trend", summary="", topic="AI", viral_score=0.9, why_it_matters=""),
            ViralIdea(title="Crypto Boom", summary="", topic="Crypto", viral_score=0.7, why_it_matters=""),
        ])
        service = ViralService(repo)
        # query falls back to topic filter
        results = service.list_ideas(query="AI")
        assert len(results) == 1
        assert results[0].topic == "AI"

    def test_list_ideas_returns_responses(self, repo: ViralRepository):
        from app.services.viral_service import ViralService

        # Seed some data
        items = [_make_item(source="rss", title=f"Article {i}") for i in range(3)]
        repo.save_content_items(items)

        idea = ViralIdea(
            title="Test Trend",
            summary="Summary here",
            topic="AI",
            source_platforms=["rss"],
            viral_score=0.85,
            novelty_score=0.7,
            momentum_score=0.6,
            cross_source_score=0.5,
            engagement_score=0.9,
            evidence=["Evidence point"],
            why_it_matters="It matters because it does",
            suggested_angles=["Angle 1"],
        )
        repo.save_idea(idea)

        service = ViralService(repo)
        results = service.list_ideas()
        assert len(results) == 1
        assert results[0].viral_score == 0.85
        assert results[0].title == "Test Trend"
