"""Web integration: real HTTP fetching and provider-backed search.

``WebConnector`` implements ``web.fetch`` with the shared HTTP client and
``web.search`` behind a :class:`SearchProvider` abstraction so the search
provider can be changed later. Search results are never fabricated — with
no configured provider, ``web.search`` reports itself unavailable.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol
from urllib.parse import urljoin, urlparse

from app.agents.permissions import Permission
from app.integrations.exceptions import CapabilityUnavailableError
from app.integrations.http_client import (
    HttpClient,
    HttpResponse,
)
from app.integrations.integration_connector import IntegrationConnector

#: Tags whose content is treated as block text when extracting HTML.
_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "nav", "main",
    "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "blockquote",
}


@dataclass(frozen=True, slots=True)
class WebPage:
    """A normalized fetched web page."""

    url: str
    status: int
    content_type: str | None
    title: str
    text: str
    html: str = ""
    redirected_from: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One structured search hit."""

    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class SearchResults:
    """A structured page of search results."""

    query: str
    results: tuple[SearchResult, ...] = field(default_factory=tuple)
    provider: str = ""


class SearchProvider(Protocol):
    """Abstraction over a web search provider."""

    name: str

    def search(self, query: str, limit: int = 10) -> SearchResults: ...


def extract_page_text(html_text: str) -> str:
    """Strip tags/scripts/styles from HTML and return normalized text."""
    import html.parser

    class _TextExtractor(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self._skip_depth = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in ("script", "style", "noscript"):
                self._skip_depth += 1
            if tag in _BLOCK_TAGS and self._skip_depth == 0:
                self.parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in ("script", "style", "noscript") and self._skip_depth:
                self._skip_depth -= 1

        def handle_data(self, data: str) -> None:
            if self._skip_depth == 0 and data.strip():
                self.parts.append(data)

    extractor = _TextExtractor()
    try:
        extractor.feed(html_text or "")
    except Exception:  # noqa: BLE001 - malformed HTML must not fail a fetch
        return ""
    text = re.sub(r"[ \t]+", " ", "".join(extractor.parts))
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def extract_title(html_text: str) -> str:
    """Return the document <title> text, if any."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if match is None:
        return ""
    return html_module.unescape(match.group(1)).strip()


class DuckDuckGoSearchProvider:
    """Real search provider backed by DuckDuckGo's HTML endpoint.

    No API key is required. Results are parsed from the returned SERP;
    no results are ever fabricated. The HTTP client is injectable so tests
    can serve a fixture response.
    """

    name = "duckduckgo"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def search(self, query: str, limit: int = 10) -> SearchResults:
        if not query.strip():
            raise ValueError("search query is required")
        endpoint = "https://html.duckduckgo.com/html/"
        response = self.client.fetch(endpoint, headers={"Content-Type": "application/x-www-form-urlencoded"}, body=f"q={query}".encode(), method="POST")
        results = self._parse_results(response.text)
        return SearchResults(query=query, results=tuple(results[:limit]), provider=self.name)

    @staticmethod
    def _parse_results(html_text: str) -> list[SearchResult]:
        """Parse DuckDuckGo HTML result blocks into structured hits."""
        results: list[SearchResult] = []
        # Each result block is an <a class="result__a"> title plus a
        # <a class="result__snippet"> snippet inside a result__body div.
        for block in re.split(r'class="result results_links', html_text)[1:]:
            title_match = re.search(r'class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
            if title_match is None:
                continue
            title = html_module.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
            url_match = re.search(r'class="result__url"[^>]*>(.*?)</a>', block, re.DOTALL)
            url = ""
            if url_match is None:
                link_match = re.search(r'href="([^"]+)"[^>]*class="result__a"', block)
                if link_match is not None:
                    url = html_module.unescape(link_match.group(1))
            else:
                url = html_module.unescape(re.sub(r"<[^>]+>", "", url_match.group(1))).strip()
            if url and not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
            snippet = ""
            if snippet_match is not None:
                snippet = html_module.unescape(re.sub(r"<[^>]+>", "", snippet_match.group(1))).strip()
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet))
        return results


class WebConnector(IntegrationConnector):
    """Real HTTP fetch and provider-backed search."""

    required_env_vars: tuple[str, ...] = ()
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "web.fetch": Permission.READ_WEBSITE,
        "web.search": Permission.READ_WEBSITE,
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        search_provider: SearchProvider | None = None,
    ) -> None:
        super().__init__(
            name="web",
            description="Real HTTP fetch and web search integration",
        )
        self.client = client or HttpClient()
        self.search_provider = search_provider

    def _capabilities(self) -> tuple[str, ...]:
        return ("web.fetch", "web.search")

    def capability_available(self, capability: str) -> tuple[bool, str]:
        if capability == "web.search":
            if self.search_provider is None:
                return False, "no search provider configured (set GOALOS_SEARCH_PROVIDER)"
            return True, "available"
        return super().capability_available(capability)

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "web.fetch":
            page = self.fetch(
                params["url"],
                max_bytes=int(params.get("max_bytes") or 0) or None,
            )
            return {
                "url": page.url,
                "status": page.status,
                "content_type": page.content_type,
                "title": page.title,
                "text": page.text,
                "word_count": len(page.text.split()),
            }
        if capability == "web.search":
            query = params["query"]
            limit = int(params.get("limit") or 10)
            results = self.search(query, limit=limit)
            return {
                "query": results.query,
                "provider": results.provider,
                "results": [
                    {"title": item.title, "url": item.url, "snippet": item.snippet}
                    for item in results.results
                ],
                "result_count": len(results.results),
            }
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    def fetch(
        self,
        url: str,
        *,
        timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> WebPage:
        """Fetch a URL and return a normalized page.

        Raises:
            HttpConnectionError, HttpTimeoutError, HttpStatusError,
            HttpResponseTooLargeError: transport-level failures.
        """
        response = self.client.fetch(
            url, timeout=timeout, max_bytes=max_bytes
        )
        if not self._is_html(response):
            return WebPage(
                url=response.url,
                status=response.status,
                content_type=response.content_type,
                title="",
                text=response.text,
                html=response.text,
            )
        html_text = response.text
        return WebPage(
            url=response.url,
            status=response.status,
            content_type=response.content_type,
            title=extract_title(html_text),
            text=extract_page_text(html_text),
            html=html_text,
        )

    def search(self, query: str, limit: int = 10) -> SearchResults:
        """Search the web through the configured provider.

        Raises:
            CapabilityUnavailableError: If no search provider is configured.
        """
        if self.search_provider is None:
            raise CapabilityUnavailableError(
                "web.search requires a configured search provider"
            )
        return self.search_provider.search(query, limit=limit)

    @staticmethod
    def _is_html(response: HttpResponse) -> bool:
        content_type = (response.content_type or "").lower()
        return "html" in content_type or content_type in ("", "text/plain")

    @staticmethod
    def resolve_url(base: str, href: str) -> str | None:
        """Resolve a possibly-relative href against a base URL."""
        try:
            parsed = urlparse(href)
        except ValueError:
            return None
        if parsed.scheme not in ("", "http", "https"):
            return None
        resolved = urljoin(base, href)
        try:
            return urlparse(resolved).geturl()
        except ValueError:
            return None
