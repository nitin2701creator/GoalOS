"""Website integration: a real same-domain SEO crawler.

``WebsiteConnector`` fetches a site's pages through the shared web
connector, discovers internal links, respects same-domain and depth/page
limits, and extracts the signals an SEO agent needs (title, meta
description, H1, canonical, robots, status, word count, links) plus
deterministic technical findings. Results are structured JSON — never
fabricated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import urlparse

from app.agents.permissions import Permission
from app.integrations.integration_connector import IntegrationConnector
from app.integrations.web import WebConnector

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESCRIPTION_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']',
    re.IGNORECASE,
)
_ROBOTS_RE = re.compile(
    r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE,
)
_HREF_RE = re.compile(r'href=["\']([^"\'#]+)["\']', re.IGNORECASE)

_SKIP_PREFIXES = ("mailto:", "tel:", "javascript:", "data:", "ftp:")
_HTML_EXTENSIONS = (".html", ".htm", ".php", "/")
_SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js",
    ".pdf", ".zip", ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".xml",
)


@dataclass(frozen=True, slots=True)
class CrawledPage:
    """Structured SEO signals extracted from one crawled page."""

    url: str
    status: int
    title: str
    meta_description: str
    h1s: tuple[str, ...]
    canonical: str
    robots: tuple[str, ...]
    word_count: int
    internal_links: tuple[str, ...]
    external_links: tuple[str, ...]
    content_length: int
    findings: tuple[str, ...]
    depth: int = 0


@dataclass(frozen=True, slots=True)
class SiteCrawl:
    """The full result of crawling one site."""

    start_url: str
    pages: tuple[CrawledPage, ...]
    total_pages: int
    errors: tuple[str, ...] = ()
    robots: dict[str, Any] = field(default_factory=dict)


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


class WebsiteConnector(IntegrationConnector):
    """Same-domain SEO crawler for real website analysis."""

    required_env_vars: tuple[str, ...] = ()
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "website.crawl": Permission.READ_WEBSITE,
        "website.analyze": Permission.READ_WEBSITE,
    }

    def __init__(self, web: WebConnector | None = None) -> None:
        super().__init__(
            name="website",
            description="Same-domain SEO website crawler",
        )
        self.web = web or WebConnector()

    def _capabilities(self) -> tuple[str, ...]:
        return ("website.crawl", "website.analyze")

    def capability_available(self, capability: str) -> tuple[bool, str]:
        if capability not in self.capabilities:
            return False, f"capability '{capability}' is not supported"
        return True, "available"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        url = params["url"]
        max_pages = max(1, int(params.get("max_pages") or 20))
        max_depth = max(0, int(params.get("max_depth") or 2))
        crawl = self.crawl(url, max_pages=max_pages, max_depth=max_depth)
        return {
            "start_url": crawl.start_url,
            "total_pages": crawl.total_pages,
            "pages": [
                {
                    "url": page.url,
                    "status": page.status,
                    "title": page.title,
                    "meta_description": page.meta_description,
                    "h1s": list(page.h1s),
                    "canonical": page.canonical,
                    "robots": list(page.robots),
                    "word_count": page.word_count,
                    "internal_links": list(page.internal_links),
                    "external_links": list(page.external_links),
                    "content_length": page.content_length,
                    "findings": list(page.findings),
                    "depth": page.depth,
                }
                for page in crawl.pages
            ],
            "errors": list(crawl.errors),
            "robots": crawl.robots,
        }

    def crawl(
        self,
        start_url: str,
        *,
        max_pages: int = 20,
        max_depth: int = 2,
    ) -> SiteCrawl:
        """Crawl ``start_url`` within its own domain.

        BFS over internal links honoring page and depth limits, fetching
        through the shared web connector. Robots.txt is fetched once for
        the root and included as information (never used to block).
        """
        base_netloc = self._normalize_netloc(urlparse(start_url).netloc)
        if not base_netloc:
            raise ValueError(f"invalid start URL: {start_url}")

        robots = self._fetch_robots(start_url)
        pages: dict[str, CrawledPage] = {}
        errors: list[str] = []
        queue: list[tuple[str, int]] = [(start_url, 0)]

        while queue and len(pages) < max_pages:
            url, depth = queue.pop(0)
            if url in pages:
                continue
            if depth > max_depth:
                continue
            page, page_errors = self._crawl_page(url, depth, base_netloc)
            if page is None:
                errors.extend(page_errors)
                continue
            pages[url] = page
            if len(pages) >= max_pages:
                break
            for link in page.internal_links:
                if link not in pages and depth + 1 <= max_depth:
                    queue.append((link, depth + 1))

        return SiteCrawl(
            start_url=start_url,
            pages=tuple(sorted(pages.values(), key=lambda item: item.url)),
            total_pages=len(pages),
            errors=tuple(errors),
            robots=robots,
        )

    def _crawl_page(
        self, url: str, depth: int, base_netloc: str
    ) -> tuple[CrawledPage | None, list[str]]:
        errors: list[str] = []
        try:
            page = self.web.fetch(url)
        except Exception as exc:  # noqa: BLE001 - crawl errors are recorded per page
            errors.append(f"{url}: {exc}")
            return None, errors
        if not self.web._is_html(page):
            return None, errors
        return self._analyze(page, depth, base_netloc), errors

    def _analyze(
        self,
        page: Any,
        depth: int,
        base_netloc: str,
    ) -> CrawledPage:
        html_text = page.html or ""
        title = self._extract_title(html_text) or page.title
        meta_description = self._extract_meta_description(html_text)
        h1s = tuple(self._clean(_strip_tags(match)) for match in _H1_RE.findall(html_text))
        h1s = tuple(item for item in h1s if item)
        canonical = self._extract_canonical(html_text)
        robots = tuple(
            part.strip().casefold()
            for part in re.split(r"[,;\s]+", self._extract_robots(html_text))
            if part.strip()
        )
        internal: list[str] = []
        external: list[str] = []
        for raw_href in _HREF_RE.findall(html_text):
            if raw_href.startswith(_SKIP_PREFIXES):
                continue
            resolved = WebConnector.resolve_url(page.url, raw_href)
            if resolved is None:
                continue
            if self._is_html_resource(resolved) and self._same_domain(resolved, base_netloc):
                if resolved not in internal:
                    internal.append(resolved)
            elif (
                urlparse(resolved).netloc
                and not self._same_domain(resolved, base_netloc)
                and resolved not in external
            ):
                external.append(resolved)

        word_count = len(page.text.split())
        findings = self._findings(
            url=page.url,
            status=page.status,
            title=title,
            meta_description=meta_description,
            h1_count=len(h1s),
            canonical=canonical,
            robots=robots,
            word_count=word_count,
        )
        return CrawledPage(
            url=page.url,
            status=page.status,
            title=title,
            meta_description=meta_description,
            h1s=h1s,
            canonical=canonical,
            robots=robots,
            word_count=word_count,
            internal_links=tuple(internal),
            external_links=tuple(external),
            content_length=len(html_text),
            findings=tuple(findings),
            depth=depth,
        )

    @staticmethod
    def _findings(
        *,
        url: str,
        status: int,
        title: str,
        meta_description: str,
        h1_count: int,
        canonical: str,
        robots: tuple[str, ...],
        word_count: int,
    ) -> list[str]:
        findings: list[str] = []
        if status >= 400:
            findings.append(f"HTTP {status} error status")
        if url.startswith("http://"):
            findings.append("served over HTTP instead of HTTPS")
        if not title:
            findings.append("missing <title>")
        elif len(title) > 60:
            findings.append("title exceeds 60 characters")
        if not meta_description:
            findings.append("missing meta description")
        elif len(meta_description) > 160:
            findings.append("meta description exceeds 160 characters")
        if h1_count == 0:
            findings.append("missing H1")
        elif h1_count > 1:
            findings.append(f"multiple H1s ({h1_count})")
        if not canonical:
            findings.append("missing canonical tag")
        if "noindex" in robots:
            findings.append("page is noindexed")
        if word_count < 300:
            findings.append(f"thin content ({word_count} words)")
        return findings

    def _fetch_robots(self, start_url: str) -> dict[str, Any]:
        parsed = urlparse(start_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = self.web.fetch(robots_url)
        except Exception:  # noqa: BLE001 - robots.txt is informational
            return {}
        disallow: list[str] = []
        allow: list[str] = []
        for line in response.text.splitlines():
            lowered = line.strip().lower()
            if lowered.startswith("disallow:"):
                disallow.append(line.split(":", 1)[1].strip())
            elif lowered.startswith("allow:"):
                allow.append(line.split(":", 1)[1].strip())
        return {
            "url": robots_url,
            "status": response.status,
            "disallow": disallow,
            "allow": allow,
        }

    @staticmethod
    def _normalize_netloc(netloc: str) -> str:
        normalized = (netloc or "").split(":")[0].lower()
        normalized = normalized.removeprefix("www.")
        return normalized

    def _same_domain(self, url: str, base_netloc: str) -> bool:
        netloc = self._normalize_netloc(urlparse(url).netloc)
        return bool(netloc) and (
            netloc == base_netloc or netloc.endswith(f".{base_netloc}")
        )

    @staticmethod
    def _is_html_resource(url: str) -> bool:
        path = urlparse(url).path.casefold()
        if not path or path.endswith(_HTML_EXTENSIONS):
            return True
        return not path.endswith(_SKIP_EXTENSIONS)

    @staticmethod
    def _extract_title(html_text: str) -> str:
        match = _TITLE_RE.search(html_text)
        return _strip_tags(match.group(1)) if match else ""

    @staticmethod
    def _extract_meta_description(html_text: str) -> str:
        match = _META_DESCRIPTION_RE.search(html_text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_canonical(html_text: str) -> str:
        match = _CANONICAL_RE.search(html_text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_robots(html_text: str) -> str:
        match = _ROBOTS_RE.search(html_text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
