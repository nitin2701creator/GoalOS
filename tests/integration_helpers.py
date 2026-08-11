"""Hermetic HTTP transport helpers for GoalOS integration tests.

A fake ``urlopen`` serves fixture responses so the REAL web fetch, crawl,
and search pipelines execute end to end without touching the network.
"""

from __future__ import annotations

import io
from typing import Any


class FakeResponse:
    """Mimic the parts of an ``http.client.HTTPResponse`` the client uses."""

    def __init__(self, body: bytes, url: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        self._body = io.BytesIO(body)
        self.status = status
        self._url = url
        self.headers = {"Content-Type": content_type}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        self._body.close()


SERP_HTML = """
<html><body>
<div class="result results_links">
  <a class="result__a" href="http://example.com/organigram-seo">Organigram SEO Guide</a>
  <a class="result__url">example.com/organigram-seo</a>
  <a class="result__snippet">A complete guide to optimizing the Organigram website.</a>
</div>
<div class="result results_links">
  <a class="result__a" href="http://example.com/keyword-tips">Keyword Research Best Practices</a>
  <a class="result__url">example.com/keyword-tips</a>
  <a class="result__snippet">How to research keywords that actually rank.</a>
</div>
<div class="result results_links">
  <a class="result__a" href="http://example.com/cannabis-trends">Cannabis Industry Trends</a>
  <a class="result__url">example.com/cannabis-trends</a>
  <a class="result__snippet">Trends shaping the cannabis industry this year.</a>
</div>
</body></html>
"""

HOMEPAGE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <title>Organigram - Premium Cannabis Products</title>
  <meta name="description" content="Organigram produces premium cannabis products with a focus on quality.">
  <link rel="canonical" href="https://www.organigram.com/">
  <meta name="robots" content="index, follow">
</head>
<body>
  <h1>Welcome to Organigram</h1>
  <p>Organigram is a leading producer of premium cannabis, operating modern facilities
  with a strong commitment to quality and consistency. Our products serve patients and
  consumers across Canada, and our team focuses on innovation, cultivation excellence,
  and responsible growth every single day.</p>
  <a href="/about">About Us</a>
  <a href="https://www.organigram.com/contact">Contact</a>
  <a href="https://external.example.org/">External site</a>
  <a href="mailto:hello@organigram.com">Email</a>
</body>
</html>
"""

ABOUT_HTML = """
<!doctype html>
<html lang="en">
<head>
  <title>About Organigram</title>
  <meta name="description" content="Learn about Organigram's history and operations.">
  <link rel="canonical" href="https://www.organigram.com/about">
</head>
<body>
  <h1>About Organigram</h1>
  <h1>Our story</h1>
  <p>Organigram has grown from a small licensed producer into a leading cannabis company,
  investing in research, new product formats, and sustainable growing practices across
  every one of our facilities. We are proud of our team and the products we bring to
  market for consumers across the country.</p>
  <a href="/">Home</a>
</body>
</html>
"""

ROBOTS_TXT = b"User-agent: *\nDisallow: /private\nAllow: /public\n"

_SITES: dict[str, tuple[bytes, str]] = {
    "https://www.organigram.com/": (HOMEPAGE_HTML.encode(), "text/html; charset=utf-8"),
    "https://www.organigram.com/about": (ABOUT_HTML.encode(), "text/html; charset=utf-8"),
    "https://www.organigram.com/contact": (HOMEPAGE_HTML.encode(), "text/html; charset=utf-8"),
    "https://www.organigram.com/robots.txt": (ROBOTS_TXT, "text/plain"),
}


class FakeUrlOpener:
    """Serve fixture responses keyed by URL, raising for anything else."""

    def __init__(self, sites: dict[str, tuple[bytes, str]] | None = None) -> None:
        self.sites = sites or dict(_SITES)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: Any, timeout: float | None = None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        self.calls.append((method, url))
        if "html.duckduckgo.com" in url:
            return FakeResponse(SERP_HTML.encode(), url)
        normalized = url.rstrip("/")
        for site_url, (body, content_type) in self.sites.items():
            if normalized == site_url.rstrip("/"):
                return FakeResponse(body, url, content_type=content_type)
        # Unknown URLs return a real 404 so the crawler records the status.
        return FakeResponse(b"Not Found", url, status=404)


def make_fake_opener() -> FakeUrlOpener:
    """Return a fresh fake opener recording every request it serves."""
    return FakeUrlOpener()
