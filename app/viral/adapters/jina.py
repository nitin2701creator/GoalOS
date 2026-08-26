"""Jina Reader web extraction adapter for the Viral Idea Finder.

Uses the Jina Reader API (r.jina.ai) to extract clean content from
web pages.  The API requires no key for basic use; set
``GOALOS_JINA_API_KEY`` for higher rate limits.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

from app.viral.adapters.base import NormalizedItem, SourceAdapter

logger = logging.getLogger(__name__)

JINA_SEARCH_URL = "https://s.jina.ai/{query}"
JINA_READER_URL = "https://r.jina.ai/{url}"


class JinaAdapter(SourceAdapter):
    """Adapter using Jina Reader for web content extraction."""

    source_name = "jina"

    def __init__(self) -> None:
        self._api_key = os.getenv("GOALOS_JINA_API_KEY", "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def search(self, query: str, max_items: int = 20) -> list[NormalizedItem]:
        """Search the web via Jina Search API and normalize results."""
        items: list[NormalizedItem] = []
        try:
            url = JINA_SEARCH_URL.format(query=query)
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()

            results = data if isinstance(data, list) else data.get("data", [])
            for result in results[:max_items]:
                if not isinstance(result, dict):
                    continue
                items.append(
                    NormalizedItem(
                        source="jina",
                        source_url=result.get("url", ""),
                        title=result.get("title", ""),
                        description=result.get("content", result.get("description", "")),
                        author=result.get("author"),
                        published_at=self._parse_date(result.get("publishedDate")),
                        metadata={
                            "jina_score": result.get("score"),
                            "jina_provider": result.get("provider"),
                        },
                    )
                )
        except Exception:
            logger.debug("Jina search failed for query: %s", query, exc_info=True)
        return items

    async def collect(self, url: str) -> NormalizedItem | None:
        """Extract content from a single URL via Jina Reader."""
        try:
            reader_url = JINA_READER_URL.format(url=url)
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(reader_url, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()

            title = data.get("title", "")
            content = data.get("content", "")
            metadata = data.get("metadata", {})

            return NormalizedItem(
                source="jina",
                source_url=url,
                title=title,
                description=content[:2000] if content else "",
                author=metadata.get("author"),
                published_at=self._parse_date(metadata.get("date")),
                language=metadata.get("language"),
                metadata={"jina_collected": True},
            )
        except Exception:
            logger.debug("Jina collect failed for URL: %s", url, exc_info=True)
            return None

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None
