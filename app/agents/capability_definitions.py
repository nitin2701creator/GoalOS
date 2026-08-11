"""Structured capability definitions for the GoalOS capability engine.

A :class:`CapabilityDefinition` is the persistent, validated contract
behind one resolvable capability: name, description, category, version,
required permissions, input/output schemas, provider type, provider,
implementation reference, and the catalog capability used to build an
executing agent. The seed catalog is data, not code: it reuses the
existing capability/skill catalog where a capability maps to a skill, and
declares integration-backed capabilities that dispatch to the existing
integration connectors.

Capabilities without a configured implementation (OCR, video generation,
WhatsApp, memory, ...) are registered but report an honest
``INTEGRATION_NOT_CONFIGURED`` — never a fabricated result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.capabilities import CAPABILITY_CATALOG, catalog_keywords
from app.agents.permissions import Permission
from app.compat import StrEnum


class CapabilityProviderType(StrEnum):
    """How a capability executes.

    Attributes:
        NATIVE: Deterministic in-process implementation (no integration).
        SKILL: Executes through a catalog skill implementation, which may
            call real integrations when configured.
        INTEGRATION: Dispatches directly to an integration connector
            capability (``system.action``).
    """

    NATIVE = "native"
    SKILL = "skill"
    INTEGRATION = "integration"


class CapabilityDefinition(BaseModel):
    """A validated, persisted capability contract.

    Attributes:
        name: Unique capability name (e.g. ``web_search``, ``seo_audit``).
        description: Human-readable summary.
        category: Functional category (seo, research, commerce, ...).
        version: Definition version.
        required_permissions: Permissions an executor must hold.
        input_schema: Structured input contract.
        output_schema: Structured output contract.
        provider_type: How the capability executes.
        provider: Provider name (integration registry name or ``native``).
        implementation: Connector capability (``web.search``) or skill
            name the capability dispatches to; ``None`` when no
            implementation is configured.
        execution_capability: Catalog capability used to build/reuse the
            executing agent (``None`` for direct-execution-only
            capabilities).
        keywords: Deterministic match keywords for goal resolution.
        enabled: Whether the capability may be resolved/executed.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: str = "general"
    version: str = "1.0"
    required_permissions: tuple[Permission, ...] = ()
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    provider_type: CapabilityProviderType
    provider: str = "native"
    implementation: str | None = None
    execution_capability: str | None = None
    keywords: tuple[str, ...] = ()
    enabled: bool = True


def _skill_definition(name: str) -> CapabilityDefinition:
    """Derive a capability definition from an existing catalog capability.

    Catalog capabilities map to their skill implementation; the provider
    is the first integration the capability requires (``native`` when
    none), and keywords come from the deterministic keyword catalog.
    """
    spec = CAPABILITY_CATALOG[name]
    provider = spec.integrations[0] if spec.integrations else "native"
    return CapabilityDefinition(
        name=name,
        description=f"Capability backed by the {name} skill.",
        category=_CATEGORY.get(name, "general"),
        required_permissions=spec.permissions,
        input_schema=_SCHEMAS.get(name, ({}, {}))[0],
        output_schema=_SCHEMAS.get(name, ({}, {}))[1],
        provider_type=(
            CapabilityProviderType.SKILL
            if spec.integrations
            else CapabilityProviderType.NATIVE
        ),
        provider=provider,
        implementation=spec.skill,
        execution_capability=name,
        keywords=catalog_keywords(name),
    )


#: Category labels for catalog-backed capabilities.
_CATEGORY: dict[str, str] = {
    "calculation": "development",
    "keyword_research": "seo",
    "website_analysis": "seo",
    "content_analysis": "content",
    "web_research": "research",
    "company_discovery": "research",
    "contact_extraction": "sales",
    "lead_qualification": "sales",
    "email_drafting": "communication",
    "sales_analysis": "commerce",
}

#: Input/output schemas for catalog-backed capabilities.
_SCHEMAS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "calculation": ({"a": "number", "b": "number", "operation": "string"}, {"result": "number"}),
    "keyword_research": ({"topic": "string"}, {"keywords": ["string"]}),
    "website_analysis": ({"url": "string"}, {"findings": ["string"], "score": "number"}),
    "content_analysis": ({"content": "string"}, {"word_count": "number", "summary": "string"}),
    "web_research": ({"query": "string"}, {"findings": ["string"]}),
    "company_discovery": ({"industry": "string", "region": "string"}, {"companies": ["string"]}),
    "contact_extraction": ({"text": "string"}, {"contacts": ["string"]}),
    "lead_qualification": ({"lead": "string", "criteria": ["string"]}, {"score": "number", "qualified": "boolean"}),
    "email_drafting": ({"recipient": "string", "subject": "string", "outline": "string"}, {"subject": "string", "body": "string"}),
    "sales_analysis": ({"topic": "string", "start_date": "string", "end_date": "string"}, {"summary": "string", "products": ["string"], "analytics": "object"}),
}


def _integration_definition(
    name: str,
    *,
    description: str,
    category: str,
    provider: str,
    implementation: str,
    permissions: tuple[Permission, ...],
    execution_capability: str | None,
    keywords: tuple[str, ...],
) -> CapabilityDefinition:
    """Build an integration-backed capability definition."""
    return CapabilityDefinition(
        name=name,
        description=description,
        category=category,
        required_permissions=permissions,
        provider_type=CapabilityProviderType.INTEGRATION,
        provider=provider,
        implementation=implementation,
        execution_capability=execution_capability,
        keywords=keywords,
    )


#: Placeholder capabilities with no configured implementation yet. They are
#: registered so resolution finds them, and honestly report
#: INTEGRATION_NOT_CONFIGURED until a provider/implementation is wired.
def _placeholder(
    name: str,
    description: str,
    category: str,
    permissions: tuple[Permission, ...],
    keywords: tuple[str, ...],
    *,
    provider: str = "native",
) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name,
        description=description,
        category=category,
        required_permissions=permissions,
        provider_type=CapabilityProviderType.INTEGRATION,
        provider=provider,
        implementation=None,
        execution_capability=None,
        keywords=keywords,
    )


#: Built-in capability definitions keyed by name. Seeded idempotently into
#: the persistent capability registry on first use.
BUILTIN_CAPABILITIES: dict[str, CapabilityDefinition] = {
    name: _skill_definition(name) for name in CAPABILITY_CATALOG
}
BUILTIN_CAPABILITIES.update(
    {
        # --- Web / SEO (integration-backed, execute through connectors) ---
        "web_search": _integration_definition(
            name="web_search",
            description="Search the web for a query through the configured search provider.",
            category="research",
            provider="web",
            implementation="web.search",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability="web_research",
            keywords=("web search", "search", "find", "research", "google it"),
        ),
        "web_fetch": _integration_definition(
            name="web_fetch",
            description="Fetch a single web page with status and content-type handling.",
            category="research",
            provider="web",
            implementation="web.fetch",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability="website_analysis",
            keywords=("fetch", "http", "download", "web page"),
        ),
        "website_crawl": _integration_definition(
            name="website_crawl",
            description="Crawl a same-domain website for pages, links, and SEO signals.",
            category="seo",
            provider="website",
            implementation="website.crawl",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability="website_analysis",
            keywords=("crawl", "website", "site", "links", "pages"),
        ),
        "website_analyze": _integration_definition(
            name="website_analyze",
            description="Analyze a website's technical SEO signals and findings.",
            category="seo",
            provider="website",
            implementation="website.analyze",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability="website_analysis",
            keywords=("analyze website", "audit website", "on-page", "website analysis"),
        ),
        "seo_audit": _integration_definition(
            name="seo_audit",
            description="Audit a website's SEO: crawl, technical findings, and recommendations.",
            category="seo",
            provider="website",
            implementation="website.analyze",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability="website_analysis",
            keywords=("seo", "audit", "technical seo", "rank", "search engine"),
        ),
        # --- Analytics / commerce ---
        "google_analytics_read": _integration_definition(
            name="google_analytics_read",
            description="Read GA4 reports (traffic, dimensions, metrics, date ranges).",
            category="analytics",
            provider="google_analytics",
            implementation="analytics.report",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability="sales_analysis",
            keywords=("analytics", "google analytics", "traffic", "report", "sessions"),
        ),
        "woocommerce_read": _integration_definition(
            name="woocommerce_read",
            description="Read WooCommerce products, orders, customers, and inventory.",
            category="commerce",
            provider="woocommerce",
            implementation="woocommerce.products",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability="sales_analysis",
            keywords=("woocommerce", "products", "inventory", "store", "orders", "stock"),
        ),
        # --- Email ---
        "gmail_read": _integration_definition(
            name="gmail_read",
            description="Search and read Gmail messages.",
            category="communication",
            provider="gmail",
            implementation="email.search",
            permissions=(Permission.READ_EMAIL,),
            execution_capability="contact_extraction",
            keywords=("email", "gmail", "inbox", "messages", "read mail"),
        ),
        "gmail_send": _integration_definition(
            name="gmail_send",
            description="Send an email through Gmail (requires explicit SEND_EMAIL authorization).",
            category="communication",
            provider="gmail",
            implementation="email.send",
            permissions=(Permission.SEND_EMAIL,),
            execution_capability="email_drafting",
            keywords=("send email", "gmail send", "outreach email", "email campaign"),
        ),
        # --- Meta Ads ---
        "meta_ads_read": _integration_definition(
            name="meta_ads_read",
            description="Read Meta ad accounts, campaigns, ad sets, ads, and insights.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.ads.read",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("meta ads", "facebook ads", "instagram ads", "campaign", "ad account"),
        ),
        "meta_ads_create": _integration_definition(
            name="meta_ads_create",
            description="Create/modify Meta campaigns and budgets (requires explicit MODIFY_ADS authorization).",
            category="advertising",
            provider="meta_ads",
            implementation="meta.campaigns.write",
            permissions=(Permission.MODIFY_ADS,),
            execution_capability=None,
            keywords=("create campaign", "meta ads", "boost", "ad budget", "spend"),
        ),
        # --- Placeholders: registered honestly, not configured ---
        "whatsapp_send": _placeholder(
            "whatsapp_send",
            "Send a WhatsApp message (provider not configured).",
            "communication",
            (Permission.SEND_WHATSAPP,),
            ("whatsapp", "chat message", "text message"),
            provider="whatsapp",
        ),
        "document_extract": _placeholder(
            "document_extract",
            "Extract structured text from a document (provider not configured).",
            "document",
            (Permission.READ_FILES,),
            ("document", "pdf", "extract text"),
        ),
        "ocr": _placeholder(
            "ocr",
            "Optical character recognition on images (provider not configured).",
            "document",
            (Permission.READ_FILES,),
            ("ocr", "scan", "image text"),
        ),
        "voice_transcription": _placeholder(
            "voice_transcription",
            "Transcribe audio/voice to text (provider not configured).",
            "media",
            (Permission.READ_FILES,),
            ("transcription", "audio", "voice", "transcribe"),
        ),
        "video_generation": _placeholder(
            "video_generation",
            "Generate video content (requires explicit GENERATE_MEDIA authorization).",
            "media",
            (Permission.GENERATE_MEDIA,),
            ("video", "ugc", "generate media"),
        ),
        "memory_store": _placeholder(
            "memory_store",
            "Store business knowledge in GoalOS memory (provider not configured).",
            "memory",
            (Permission.ACCESS_MEMORY,),
            ("remember", "memory", "store knowledge", "save"),
            provider="memory",
        ),
        "memory_retrieve": _placeholder(
            "memory_retrieve",
            "Retrieve business knowledge from GoalOS memory (provider not configured).",
            "memory",
            (Permission.ACCESS_MEMORY,),
            ("memory", "recall", "retrieve", "remember"),
            provider="memory",
        ),
    }
)
