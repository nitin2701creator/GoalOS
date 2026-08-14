"""Unit tests for the generic GoalOS capability restriction mechanism."""

from __future__ import annotations

from app.agents.capability_restrictions import (
    apply_capability_restrictions,
    parse_capability_restrictions,
)

#: A small known catalog mirroring the registered capability vocabulary.
KNOWN = [
    ("web_research", ("research", "find", "search", "gather", "identify")),
    ("web_search", ("web search", "search", "find", "research", "google it")),
    ("website_analysis", ("website", "site analysis", "on-page", "organigram")),
    ("website_crawl", ("crawl", "website", "site", "links", "pages")),
    ("sales_analysis", ("sales", "revenue", "order", "ecommerce", "store performance", "commerce")),
    ("woocommerce_read", ("woocommerce", "products", "inventory", "store", "orders", "stock")),
    ("google_analytics_read", ("analytics", "google analytics", "traffic", "report", "sessions")),
    ("seo_audit", ("seo", "audit", "technical seo", "rank", "search engine")),
    ("keyword_research", ("keyword", "seo", "search volume", "search term")),
]


def test_only_whitelist_parses_names() -> None:
    restrictions = parse_capability_restrictions(
        "Use ONLY the web_research capability. Search the web for competitors.",
        KNOWN,
    )
    assert restrictions.active is True
    assert restrictions.whitelist == frozenset({"web_research"})
    assert not restrictions.blacklist


def test_only_whitelist_supports_lists() -> None:
    restrictions = parse_capability_restrictions(
        "Only use web_research and keyword_research for this task.",
        KNOWN,
    )
    assert restrictions.whitelist == frozenset({"web_research", "keyword_research"})


def test_only_these_capabilities_form() -> None:
    restrictions = parse_capability_restrictions(
        "ONLY these capabilities: web_search, web_research",
        KNOWN,
    )
    assert restrictions.whitelist == frozenset({"web_search", "web_research"})


def test_do_not_use_blacklist_parses_names() -> None:
    restrictions = parse_capability_restrictions(
        "Search the web for Organigram. Do not use WooCommerce, analytics, "
        "website_analysis, or any other integration.",
        KNOWN,
    )
    assert restrictions.active is True
    assert restrictions.blacklist == frozenset(
        {"woocommerce_read", "google_analytics_read", "website_analysis"}
    )
    assert not restrictions.whitelist


def test_blacklist_supports_never_without_except() -> None:
    never = parse_capability_restrictions("Never use gmail for this.", KNOWN)
    assert never.active is False  # gmail is not part of this catalog

    without = parse_capability_restrictions(
        "Deliver the analysis without using sales_analysis.", KNOWN
    )
    assert without.blacklist == frozenset({"sales_analysis"})

    excepted = parse_capability_restrictions(
        "Use any capability except woocommerce_read.", KNOWN
    )
    assert excepted.blacklist == frozenset({"woocommerce_read"})


def test_both_restrictions_parse_together() -> None:
    restrictions = parse_capability_restrictions(
        "Use ONLY web_research. Do not use WooCommerce, analytics, or website_analysis.",
        KNOWN,
    )
    assert restrictions.whitelist == frozenset({"web_research"})
    assert restrictions.blacklist == frozenset(
        {"woocommerce_read", "google_analytics_read", "website_analysis"}
    )


def test_no_restrictions_when_absent() -> None:
    restrictions = parse_capability_restrictions(
        "Analyse Organigram's website SEO and tell me what needs to be fixed.",
        KNOWN,
    )
    assert restrictions.active is False
    assert not restrictions.whitelist
    assert not restrictions.blacklist


def test_statement_with_only_is_not_a_restriction() -> None:
    """\"We only have X configured\" must not be treated as a whitelist."""
    restrictions = parse_capability_restrictions(
        "We only have web_research and sales_analysis configured today.",
        KNOWN,
    )
    assert restrictions.active is False


def test_apply_whitelist_filters() -> None:
    matched = ["web_search", "website_crawl", "google_analytics_read", "web_research"]
    restrictions = parse_capability_restrictions(
        "Use ONLY the web_research capability.", KNOWN
    )
    filtered = apply_capability_restrictions(matched, restrictions)
    assert filtered == ["web_research"]


def test_apply_whitelist_with_resolver_keeps_implementing_capabilities() -> None:
    """A resolver maps web_search to web_research (its execution capability)."""
    matched = ["web_search", "website_crawl", "google_analytics_read", "web_research"]
    restrictions = parse_capability_restrictions(
        "Use ONLY the web_research capability.", KNOWN
    )
    filtered = apply_capability_restrictions(
        matched,
        restrictions,
        resolve={
            "web_search": {"web_search", "web_research"},
            "website_crawl": {"website_crawl", "website_analysis"},
            "google_analytics_read": {"google_analytics_read", "sales_analysis"},
            "web_research": {"web_research"},
        }.get,
    )
    assert filtered == ["web_search", "web_research"]


def test_apply_blacklist_removes() -> None:
    matched = ["web_search", "website_analysis", "google_analytics_read", "web_research"]
    restrictions = parse_capability_restrictions(
        "Search the web. Do not use website_analysis.", KNOWN
    )
    filtered = apply_capability_restrictions(matched, restrictions)
    assert filtered == ["web_search", "google_analytics_read", "web_research"]


def test_apply_blacklist_with_resolver_removes_related_capabilities() -> None:
    """A resolver maps website_crawl to its execution capability."""
    matched = ["web_search", "website_crawl", "google_analytics_read", "web_research"]
    restrictions = parse_capability_restrictions(
        "Search the web. Do not use website_analysis.", KNOWN
    )
    filtered = apply_capability_restrictions(
        matched,
        restrictions,
        resolve={
            "web_search": {"web_search", "web_research"},
            "website_crawl": {"website_crawl", "website_analysis"},
            "google_analytics_read": {"google_analytics_read", "sales_analysis"},
            "web_research": {"web_research"},
        }.get,
    )
    assert filtered == ["web_search", "google_analytics_read", "web_research"]


def test_apply_resolver_expands_related_capabilities() -> None:
    """Resolving aliases lets a prohibition remove dependent capabilities."""
    matched = ["web_research", "sales_analysis"]
    restrictions = parse_capability_restrictions(
        "Search the web. Do not use WooCommerce, analytics, or website_analysis.",
        KNOWN,
    )
    # sales_analysis requires the same integrations as woocommerce_read and
    # google_analytics_read, so it must be removed through the resolver.
    filtered = apply_capability_restrictions(
        matched,
        restrictions,
        resolve={
            "web_research": {"web_research"},
            "sales_analysis": {"sales_analysis", "woocommerce_read", "google_analytics_read"},
        }.get,
    )
    assert filtered == ["web_research"]


def test_apply_noop_without_restrictions() -> None:
    matched = ["web_research", "sales_analysis"]
    assert apply_capability_restrictions(matched, None) == matched


def test_static_catalog_resolution_honors_restrictions() -> None:
    """The deterministic catalog fallback also respects explicit restrictions."""
    from app.agents.capabilities import resolve_capabilities

    resolved = resolve_capabilities(
        "Use ONLY web_research to search for Organigram distributors. "
        "Do not use sales_analysis."
    )
    assert resolved == ("web_research",)

    # Without restrictions the same goal resolves the full capability set.
    unrestricted = resolve_capabilities(
        "Search for Organigram distributors and analyze their sales."
    )
    assert "website_analysis" in unrestricted
    assert "web_research" in unrestricted
    assert "company_discovery" in unrestricted
    assert "sales_analysis" in unrestricted
