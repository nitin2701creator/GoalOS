"""Capability analysis for the GoalOS agent factory.

A capability is a named unit of agent functionality. The catalog maps
every supported capability to the skill, permissions, and tools it
requires. ``resolve_capabilities`` translates a plain-language
requirement into an ordered set of capabilities using deterministic
keyword matching — the mapping is general, never special-cased to one
example requirement.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.capability_restrictions import (
    apply_capability_restrictions,
    parse_capability_restrictions,
)
from app.agents.permissions import Permission


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """What one capability requires of an agent.

    Attributes:
        skill: The skill name that implements the capability.
        permissions: Permissions the capability requires.
        tools: Optional tool names the capability expects.
        integrations: Integration names the capability depends on.
        integration_capabilities: Concrete connector capabilities needed
            (``system.action`` names), used for availability checks.
    """

    skill: str
    permissions: tuple[Permission, ...]
    tools: tuple[str, ...] = ()
    integrations: tuple[str, ...] = ()
    integration_capabilities: tuple[str, ...] = ()


#: Every supported capability and its implementation requirements.
CAPABILITY_CATALOG: dict[str, CapabilitySpec] = {
    "calculation": CapabilitySpec(
        skill="calculation",
        permissions=(Permission.EXECUTE_CODE,),
    ),
    "keyword_research": CapabilitySpec(
        skill="keyword_research",
        permissions=(Permission.READ_WEBSITE,),
        integrations=("web",),
        integration_capabilities=("web.search",),
    ),
    "website_analysis": CapabilitySpec(
        skill="website_analysis",
        permissions=(Permission.READ_WEBSITE,),
        integrations=("web", "website"),
        integration_capabilities=("web.fetch", "website.crawl"),
    ),
    "content_analysis": CapabilitySpec(
        skill="content_analysis",
        permissions=(Permission.READ_WEBSITE, Permission.READ_FILES),
    ),
    "web_research": CapabilitySpec(
        skill="web_research",
        permissions=(Permission.READ_WEBSITE,),
        integrations=("web",),
        integration_capabilities=("web.search",),
    ),
    "company_discovery": CapabilitySpec(
        skill="company_discovery",
        permissions=(Permission.READ_WEBSITE,),
        integrations=("web",),
        integration_capabilities=("web.search",),
    ),
    "contact_extraction": CapabilitySpec(
        skill="contact_extraction",
        permissions=(Permission.READ_WEBSITE, Permission.READ_EMAIL),
        integrations=("web", "gmail"),
        integration_capabilities=("web.search", "email.read"),
    ),
    "lead_qualification": CapabilitySpec(
        skill="lead_qualification",
        permissions=(Permission.READ_ANALYTICS,),
        integrations=("google_analytics",),
        integration_capabilities=("analytics.report",),
    ),
    "email_drafting": CapabilitySpec(
        skill="email_drafting",
        permissions=(Permission.SEND_EMAIL,),
        integrations=("gmail",),
        integration_capabilities=("email.draft",),
    ),
    "sales_analysis": CapabilitySpec(
        skill="sales_analysis",
        permissions=(Permission.READ_WEBSITE, Permission.READ_ANALYTICS),
        integrations=("woocommerce", "google_analytics"),
        integration_capabilities=("woocommerce.products", "analytics.report"),
    ),
}

#: Deterministic keyword → capability matching, in catalog order. The first
#: capability in the catalog wins when multiple keywords match.
_CAPABILITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("calculation", ("sum", "calculat", "compute", "arithmetic", "add two", "math")),
    ("keyword_research", ("keyword", "seo", "search volume", "search term")),
    ("website_analysis", ("website", "site analysis", "on-page", "organigram")),
    ("content_analysis", ("content", "copy", "analyz")),
    ("web_research", ("research", "find", "search", "gather", "identify")),
    ("company_discovery", ("company", "distributor", "vendor", "supplier", "producer")),
    ("contact_extraction", ("contact", "email address", "phone number", "extract")),
    ("lead_qualification", ("lead", "qualif", "prospect", "candidate")),
    ("email_drafting", ("draft email", "outreach", "email campaign")),
    ("sales_analysis", ("sales", "revenue", "order", "ecommerce", "store performance", "commerce")),
)


def resolve_capabilities(requirement: str) -> tuple[str, ...]:
    """Translate ``requirement`` into an ordered, de-duplicated capability set.

    Args:
        requirement: Plain-language business requirement.

    Returns:
        Matched capability names in deterministic catalog order. Explicit
        user restrictions ("use ONLY X", "do not use Y") are honored so
        prohibited capabilities are never added.
    """
    text = requirement.casefold()
    matched = [
        capability
        for capability, keywords in _CAPABILITY_KEYWORDS
        if any(keyword in text for keyword in keywords)
    ]
    restrictions = parse_capability_restrictions(requirement, _CAPABILITY_KEYWORDS)
    filtered = apply_capability_restrictions(matched, restrictions)
    return tuple(dict.fromkeys(filtered))


def capability_spec(capability: str) -> CapabilitySpec:
    """Return the catalog spec for ``capability``.

    Raises:
        ValueError: If the capability is not in the catalog.
    """
    spec = CAPABILITY_CATALOG.get(capability)
    if spec is None:
        raise ValueError(f"unsupported capability: {capability}")
    return spec


def catalog_keywords(capability: str) -> tuple[str, ...]:
    """Return the deterministic match keywords for a catalog capability."""
    for name, keywords in _CAPABILITY_KEYWORDS:
        if name == capability:
            return keywords
    return ()
