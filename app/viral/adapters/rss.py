"""RSS/Atom feed source adapter for the Viral Idea Finder.

Fetches and parses RSS 2.0 and Atom feeds, normalizing entries into
``NormalizedItem`` objects.  Uses only ``httpx`` and the standard library
xml parser — no additional dependencies.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx

from app.viral.adapters.base import NormalizedItem, SourceAdapter

logger = logging.getLogger(__name__)

# Well-known feed discovery URLs for trending RSS sources.
WELL_KNOWN_FEEDS: dict[str, str] = {
    "hacker_news": "https://hnrss.org/frontpage?count=30",
    "product_hunt": "https://www.producthunt.com/feed",
    "techcrunch": "https://techcrunch.com/feed/",
    "reddit_programming": "https://www.reddit.com/r/programming/.rss",
}

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class RSSAdapter(SourceAdapter):
    """Adapter for RSS 2.0 and Atom feeds."""

    source_name = "rss"

    async def search(self, query: str, max_items: int = 20) -> list[NormalizedItem]:
        """Search well-known RSS feeds for items matching the query.

        ``query`` is matched against title and description text.
        Returns at most ``max_items`` normalized items.
        """
        items: list[NormalizedItem] = []
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for feed_name, feed_url in WELL_KNOWN_FEEDS.items():
                try:
                    resp = await client.get(feed_url)
                    resp.raise_for_status()
                    parsed = self._parse_feed(resp.text, source_tag=f"rss:{feed_name}")
                    query_lower = query.lower()
                    for item in parsed:
                        text = f"{item.title} {item.description}".lower()
                        if query_lower in text:
                            items.append(item)
                            if len(items) >= max_items:
                                return items
                except Exception:
                    logger.debug("Failed to fetch RSS feed %s", feed_name, exc_info=True)
                    continue
        return items

    async def collect(self, url: str) -> NormalizedItem | None:
        """Fetch and normalize a single RSS/Atom URL."""
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                items = self._parse_feed(resp.text, source_tag="rss")
                return items[0] if items else None
            except Exception:
                logger.debug("Failed to collect RSS URL: %s", url, exc_info=True)
                return None

    def _parse_feed(self, xml_text: str, source_tag: str = "rss") -> list[NormalizedItem]:
        """Parse RSS 2.0 or Atom XML into normalized items."""
        items: list[NormalizedItem] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return items

        # Detect Atom vs RSS
        if root.tag == f"{_ATOM_NS}feed" or root.tag == "feed":
            items = self._parse_atom(root, source_tag)
        else:
            items = self._parse_rss(root, source_tag)
        return items

    def _parse_rss(self, root: ET.Element, source_tag: str) -> list[NormalizedItem]:
        """Parse RSS 2.0 XML."""
        items: list[NormalizedItem] = []
        for item_el in root.iter("item"):
            title = self._text(item_el, "title") or ""
            link = self._text(item_el, "link") or ""
            desc = self._text(item_el, "description") or ""
            author = self._text(item_el, "author") or self._text(item_el, "{http://purl.org/dc/elements/1.1/}creator")
            pub_date = self._parse_date(self._text(item_el, "pubDate"))

            items.append(
                NormalizedItem(
                    source=source_tag,
                    source_url=link,
                    title=title.strip(),
                    description=desc.strip(),
                    author=author.strip() if author else None,
                    published_at=pub_date,
                    engagement=self._extract_rss_engagement(item_el),
                    metadata={"feed_type": "rss"},
                )
            )
        return items

    def _parse_atom(self, root: ET.Element, source_tag: str) -> list[NormalizedItem]:
        """Parse Atom XML."""
        items: list[NormalizedItem] = []
        ns = _ATOM_NS
        for entry in root.findall(f"{ns}entry"):
            title_el = entry.find(f"{ns}title")
            title = (title_el.text or "").strip() if title_el is not None else ""

            link_el = entry.find(f"{ns}link[@rel='alternate']") or entry.find(f"{ns}link")
            link = link_el.get("href", "") if link_el is not None else ""

            summary_el = entry.find(f"{ns}summary") or entry.find(f"{ns}content")
            desc = ""
            if summary_el is not None:
                desc = (summary_el.text or "").strip()

            author_el = entry.find(f"{ns}author/{ns}name")
            author = (author_el.text or "").strip() if author_el is not None else None

            pub_el = entry.find(f"{ns}published") or entry.find(f"{ns}updated")
            pub_date = self._parse_date(pub_el.text if pub_el is not None else None)

            items.append(
                NormalizedItem(
                    source=source_tag,
                    source_url=link,
                    title=title,
                    description=desc,
                    author=author,
                    published_at=pub_date,
                    metadata={"feed_type": "atom"},
                )
            )
        return items

    @staticmethod
    def _text(el: ET.Element, tag: str) -> str | None:
        child = el.find(tag)
        return child.text if child is not None and child.text else None

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
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

    @staticmethod
    def _extract_rss_engagement(item_el: ET.Element) -> dict[str, Any]:
        """Extract engagement metrics from RSS extensions if present."""
        engagement: dict[str, Any] = {}
        # hnrss:points, hnrss:comments
        for tag, key in [
            ("{https://hnrss.org/}points", "points"),
            ("{https://hnrss.org/}comments", "comments"),
        ]:
            el = item_el.find(tag)
            if el is not None and el.text:
                try:
                    engagement[key] = int(el.text)
                except ValueError:
                    pass
        return engagement
