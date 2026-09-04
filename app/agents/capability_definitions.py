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
        requires_approval: Whether execution requires an approved workflow
            context (publishing/external writes must never run silently).
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
    requires_approval: bool = False


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
    requires_approval: bool = False,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
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
        requires_approval=requires_approval,
        input_schema=input_schema or {},
        output_schema=output_schema or {},
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
            requires_approval=True,
        ),
        # --- Meta Campaign Executor (READ capabilities) ---
        "meta_get_accounts": _integration_definition(
            name="meta_get_accounts",
            description="List Meta ad accounts accessible with the configured token.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.ads.read",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("meta accounts", "ad accounts", "facebook accounts", "list accounts"),
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {"accounts": {"type": "array"}}},
        ),
        "meta_get_campaigns": _integration_definition(
            name="meta_get_campaigns",
            description="List Meta campaigns with status, objective, and budget.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.campaigns.read",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("meta campaigns", "list campaigns", "facebook campaigns"),
            input_schema={"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}},
            output_schema={"type": "object", "properties": {"campaigns": {"type": "array"}}},
        ),
        "meta_get_adsets": _integration_definition(
            name="meta_get_adsets",
            description="List Meta ad sets with targeting, budget, and optimization settings.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.adsets.read",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("meta ad sets", "adsets", "list ad sets"),
        ),
        "meta_get_ads": _integration_definition(
            name="meta_get_ads",
            description="List Meta ads with creative and status information.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.ads.list",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("meta ads", "list ads", "facebook ads"),
        ),
        "meta_get_insights": _integration_definition(
            name="meta_get_insights",
            description="Get Meta performance insights (impressions, clicks, spend, CTR, CPC, ROAS).",
            category="advertising",
            provider="meta_ads",
            implementation="meta.insights.read",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("meta insights", "ad performance", "campaign metrics", "ad spend", "roas"),
        ),
        # --- Meta Campaign Executor (INTELLIGENCE capabilities) ---
        "meta_audit_account": _integration_definition(
            name="meta_audit_account",
            description="Run a full Meta Ads account audit: pixel/CAPI, structure, overlap, quality, targeting.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.intelligence.audit",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("meta audit", "account audit", "ads audit", "meta health check"),
        ),
        "meta_analyze_fatigue": _integration_definition(
            name="meta_analyze_fatigue",
            description="Detect creative fatigue: CTR decline, high frequency, rising CPC.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.intelligence.fatigue",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("creative fatigue", "ad fatigue", "frequency", "ctr decline"),
        ),
        "meta_research_competitors": _integration_definition(
            name="meta_research_competitors",
            description="Analyze competitor ads for hooks, offers, CTA patterns, and longevity.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.intelligence.competitors",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("competitor ads", "competitor research", "ad hooks", "ad library"),
        ),
        "meta_generate_copy": _integration_definition(
            name="meta_generate_copy",
            description="Generate 20 on-brand ad copy variations (5 angles × 4 variations).",
            category="advertising",
            provider="meta_ads",
            implementation="meta.intelligence.copy",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("ad copy", "generate copy", "ad variations", "ad headlines"),
        ),
        "meta_score_creative": _integration_definition(
            name="meta_score_creative",
            description="Score an ad creative: hook, copy, CTA, emotional pull, offer clarity, visual fit.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.intelligence.score",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("score creative", "ad score", "creative quality", "ad rating"),
        ),
        # --- Meta Campaign Executor (BUILD capabilities) ---
        "meta_build_campaign": _integration_definition(
            name="meta_build_campaign",
            description="Build a complete Meta campaign blueprint (campaign → ad set → ad → creative).",
            category="advertising",
            provider="meta_ads",
            implementation="meta.campaign.build",
            permissions=(Permission.MODIFY_ADS,),
            execution_capability=None,
            keywords=("build campaign", "create campaign structure", "campaign blueprint"),
            requires_approval=True,
        ),
        "meta_validate_campaign": _integration_definition(
            name="meta_validate_campaign",
            description="Validate a campaign blueprint before execution (no Meta API call).",
            category="advertising",
            provider="meta_ads",
            implementation="meta.campaign.validate",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("validate campaign", "check campaign", "campaign validation"),
        ),
        # --- Meta Campaign Executor (EXECUTION capabilities) ---
        "meta_dry_run": _integration_definition(
            name="meta_dry_run",
            description="Create a dry-run of a Meta action (shows what would happen, no execution).",
            category="advertising",
            provider="meta_ads",
            implementation="meta.execution.dry_run",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("dry run", "preview action", "simulation", "test action"),
        ),
        "meta_request_approval": _integration_definition(
            name="meta_request_approval",
            description="Request approval for a Meta Ads action before execution.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.execution.approve",
            permissions=(Permission.MODIFY_ADS,),
            execution_capability=None,
            keywords=("approve action", "request approval", "meta approval"),
            requires_approval=True,
        ),
        "meta_execute_action": _integration_definition(
            name="meta_execute_action",
            description="Execute an approved Meta Ads action (create/update/activate/pause/budget change).",
            category="advertising",
            provider="meta_ads",
            implementation="meta.execution.execute",
            permissions=(Permission.MODIFY_ADS,),
            execution_capability=None,
            keywords=("execute action", "run action", "meta execute", "apply change"),
            requires_approval=True,
        ),
        "meta_get_action_status": _integration_definition(
            name="meta_get_action_status",
            description="Get the status of a pending or completed Meta execution action.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.execution.status",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("action status", "execution status", "meta action status"),
        ),
        # --- Meta Campaign Executor (AUDIT capabilities) ---
        "meta_get_audit_log": _integration_definition(
            name="meta_get_audit_log",
            description="Get the audit log of all Meta Ads operations performed by GoalOS.",
            category="advertising",
            provider="meta_ads",
            implementation="meta.audit.log",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("audit log", "meta audit log", "action history", "meta history"),
        ),
        # --- Placeholders: registered honestly, not configured ---
        # --- WhatsApp (real capability, execute through OpenWA/Meta adapter) ---
        "whatsapp_send_message": _integration_definition(
            name="whatsapp_send_message",
            description="Send a WhatsApp text message through the configured provider (OpenWA/Meta Cloud).",
            category="communication",
            provider="whatsapp",
            implementation="whatsapp.send_message",
            permissions=(Permission.SEND_WHATSAPP,),
            execution_capability=None,
            keywords=("whatsapp", "send whatsapp", "whatsapp message", "chat message", "text message"),
            requires_approval=True,
        ),
        "whatsapp_send_media": _integration_definition(
            name="whatsapp_send_media",
            description="Send a WhatsApp media message (image/video/audio/document).",
            category="communication",
            provider="whatsapp",
            implementation="whatsapp.send_media",
            permissions=(Permission.SEND_WHATSAPP,),
            execution_capability=None,
            keywords=("whatsapp image", "whatsapp video", "whatsapp document", "send media"),
            requires_approval=True,
        ),
        "whatsapp_receive_message": _integration_definition(
            name="whatsapp_receive_message",
            description="Receive and process inbound WhatsApp messages via webhook.",
            category="communication",
            provider="whatsapp",
            implementation="whatsapp.receive_message",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("receive whatsapp", "inbound whatsapp", "whatsapp webhook"),
        ),
        "whatsapp_get_status": _integration_definition(
            name="whatsapp_get_status",
            description="Get WhatsApp provider connection status and configuration.",
            category="communication",
            provider="whatsapp",
            implementation="whatsapp.get_status",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("whatsapp status", "whatsapp health", "whatsapp connection"),
        ),
        "whatsapp_send_template": _integration_definition(
            name="whatsapp_send_template",
            description="Send a pre-approved WhatsApp template message.",
            category="communication",
            provider="whatsapp",
            implementation="whatsapp.send_template",
            permissions=(Permission.SEND_WHATSAPP,),
            execution_capability=None,
            keywords=("whatsapp template", "template message", "send template", "business template"),
            requires_approval=True,
        ),
        "whatsapp_analytics": _integration_definition(
            name="whatsapp_analytics",
            description="View WhatsApp conversation analytics, quality metrics, and response statistics.",
            category="analytics",
            provider="native",
            implementation="whatsapp.analytics",
            permissions=(Permission.READ_ANALYTICS,),
            execution_capability=None,
            keywords=("whatsapp analytics", "conversation metrics", "response quality", "handoff rate", "ai resolution"),
        ),
        "whatsapp_multilingual": _integration_definition(
            name="whatsapp_multilingual",
            description="Multilingual WhatsApp support with automatic language detection and response.",
            category="communication",
            provider="native",
            implementation="whatsapp.language",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("multilingual", "language detection", "hindi", "hinglish", "bengali", "tamil", "telugu"),
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
        # --- Video Production (OpenMontage-backed) ---
        "video_create_project": _integration_definition(
            name="video_create_project",
            description="Create a video production project with a brief and pipeline selection.",
            category="media",
            provider="video",
            implementation="video.create_project",
            permissions=(Permission.GENERATE_MEDIA,),
            execution_capability="video_create_project",
            keywords=("create video", "make video", "video project", "produce video", "video production"),
            requires_approval=True,
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Description of the video to create"},
                    "duration_seconds": {"type": "integer", "description": "Target duration"},
                    "pipeline": {"type": "string", "description": "Pipeline name or auto"},
                },
                "required": ["prompt"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "status": {"type": "string"},
                    "pipeline": {"type": "string"},
                },
            },
        ),
        "video_start_production": _integration_definition(
            name="video_start_production",
            description="Start production on an approved video job (OpenMontage Remotion pipeline).",
            category="media",
            provider="video",
            implementation="video.start_production",
            permissions=(Permission.GENERATE_MEDIA,),
            execution_capability="video_start_production",
            keywords=("start video", "begin production", "render video", "generate video"),
            requires_approval=True,
        ),
        "video_get_status": _integration_definition(
            name="video_get_status",
            description="Get the current status and progress of a video production job.",
            category="media",
            provider="video",
            implementation="video.get_status",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("video status", "video progress", "production status", "video job status"),
        ),
        "video_list_pipelines": _integration_definition(
            name="video_list_pipelines",
            description="List available video production pipelines (OpenMontage).",
            category="media",
            provider="video",
            implementation="video.list_pipelines",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("video pipelines", "video types", "video styles", "what kind of video"),
        ),
        "video_cancel": _integration_definition(
            name="video_cancel",
            description="Cancel a running or queued video production job.",
            category="media",
            provider="video",
            implementation="video.cancel",
            permissions=(Permission.GENERATE_MEDIA,),
            execution_capability=None,
            keywords=("cancel video", "stop production", "abort video"),
            requires_approval=True,
        ),
        "video_retry": _integration_definition(
            name="video_retry",
            description="Retry a failed video production job.",
            category="media",
            provider="video",
            implementation="video.retry",
            permissions=(Permission.GENERATE_MEDIA,),
            execution_capability=None,
            keywords=("retry video", "redo video", "try again video"),
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
        # --- Phone / Voice (planned, not configured) ---
        "phone_voice_call": _integration_definition(
            name="phone_voice_call",
            description="Initiate an outbound voice/phone call (Twilio/Plivo provider).",
            category="communication",
            provider="communications",
            implementation="phone_voice_call",
            permissions=(Permission.SEND_WHATSAPP,),
            execution_capability=None,
            keywords=("phone call", "voice call", "ai call", "outbound call", "make call"),
            requires_approval=True,
        ),
        "voice_call": _integration_definition(
            name="voice_call",
            description="Initiate an outbound voice call with full lifecycle tracking.",
            category="communication",
            provider="communications",
            implementation="voice.call",
            permissions=(Permission.SEND_WHATSAPP,),
            execution_capability=None,
            keywords=("voice call", "phone call", "call customer", "outbound call", "domestic call", "international call"),
            requires_approval=True,
        ),
        "voice_ai": _integration_definition(
            name="voice_ai",
            description="AI voice conversation with real-time STT/LLM/TTS pipeline.",
            category="communication",
            provider="native",
            implementation="voice.ai",
            permissions=(Permission.SEND_WHATSAPP,),
            execution_capability=None,
            keywords=("ai voice", "voice agent", "ai phone call", "voice conversation", "talking bot"),
            requires_approval=True,
        ),
        "voice_stt": _integration_definition(
            name="voice_stt",
            description="Speech-to-text transcription for voice calls.",
            category="communication",
            provider="native",
            implementation="voice.stt",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("speech to text", "transcription", "stt", "voice transcription", "whisper"),
        ),
        "voice_tts": _integration_definition(
            name="voice_tts",
            description="Text-to-speech synthesis for voice calls.",
            category="communication",
            provider="native",
            implementation="voice.tts",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("text to speech", "tts", "voice synthesis", "speech synthesis", "elevenlabs"),
        ),
        "voice_memory": _integration_definition(
            name="voice_memory",
            description="Store voice call summaries and outcomes in GoalOS memory.",
            category="memory",
            provider="native",
            implementation="voice.memory",
            permissions=(Permission.ACCESS_MEMORY,),
            execution_capability=None,
            keywords=("call memory", "call summary", "call notes", "voice memory", "call outcomes"),
        ),
        "voice_handoff": _integration_definition(
            name="voice_handoff",
            description="Transfer voice call to human operator when AI confidence is low.",
            category="communication",
            provider="native",
            implementation="voice.handoff",
            permissions=(Permission.SEND_WHATSAPP,),
            execution_capability=None,
            keywords=("transfer call", "human agent", "call handoff", "escalate call", "warm transfer"),
            requires_approval=True,
        ),
        "sms_send": _integration_definition(
            name="sms_send",
            description="Send an outbound SMS message (Twilio/Plivo provider).",
            category="communication",
            provider="communications",
            implementation="sms_send",
            permissions=(Permission.SEND_WHATSAPP,),
            execution_capability=None,
            keywords=("sms", "text message", "send sms", "send text"),
            requires_approval=True,
        ),
        # --- SEO (real capability, execute through web connectors) ---
        # seo_audit already exists via skill catalog; no duplicate needed.
        "seo_keyword_research": _integration_definition(
            name="seo_keyword_research",
            description="Research keyword opportunities for a topic or website.",
            category="seo",
            provider="web",
            implementation="web.search",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability="keyword_research",
            keywords=("keyword research", "keyword opportunities", "search keywords", "keyword analysis"),
        ),
        # --- Viral Idea Finder (native, real implementation) ---
        "viral_idea_finder": _integration_definition(
            name="viral_idea_finder",
            description="Discover trending content and identify potentially viral ideas across web sources.",
            category="intelligence",
            provider="native",
            implementation="viral.scan",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("viral", "trending", "trend", "viral ideas", "hot topics", "opportunity"),
        ),
        # --- Resource Monitor (native, real implementation) ---
        "resource_monitor": _integration_definition(
            name="resource_monitor",
            description="Monitor system resource utilization (CPU, RAM, disk, load) and GoalOS process health.",
            category="system",
            provider="native",
            implementation="system.resource_monitor",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("system status", "resource monitor", "server health", "cpu usage", "ram usage"),
        ),
        # --- Resource Guardian (native, production capacity monitoring) ---
        "resource_guardian": _integration_definition(
            name="resource_guardian",
            description="Production capacity monitoring with state machine, hysteresis, and upgrade recommendations. Monitors CPU, RAM, swap, disk, load, containers, and service health.",
            category="system",
            provider="native",
            implementation="system.resource_guardian",
            permissions=(Permission.READ_WEBSITE,),
            execution_capability=None,
            keywords=("infrastructure health", "capacity", "upgrade required", "resource guardian", "vps health", "server capacity", "is upgrade needed", "capacity risk"),
        ),
    }
)

#: Twenty CRM capabilities (integration-backed through TwentyConnector).
#: Reads require READ_CRM; creates/updates require WRITE_CRM (dangerous,
#: never implicit) and additionally require an approved workflow context.
_TWENTY_CAPABILITIES: dict[str, CapabilityDefinition] = {
    "twenty_search_people": _integration_definition(
        name="twenty_search_people",
        description="Search Twenty CRM people records by query/filter.",
        category="crm",
        provider="twenty",
        implementation="twenty.search_people",
        permissions=(Permission.READ_CRM,),
        execution_capability=None,
        keywords=("twenty", "crm", "people", "contacts", "find person", "search person"),
    ),
    "twenty_create_person": _integration_definition(
        name="twenty_create_person",
        description="Create a Twenty CRM person record (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.create_person",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("create person", "add contact", "new contact", "create contact"),
        requires_approval=True,
    ),
    "twenty_update_person": _integration_definition(
        name="twenty_update_person",
        description="Update a Twenty CRM person record (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.update_person",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("update person", "edit contact", "update contact"),
        requires_approval=True,
    ),
    "twenty_search_companies": _integration_definition(
        name="twenty_search_companies",
        description="Search Twenty CRM company records by query/filter.",
        category="crm",
        provider="twenty",
        implementation="twenty.search_companies",
        permissions=(Permission.READ_CRM,),
        execution_capability=None,
        keywords=("search companies", "companies", "accounts", "crm companies"),
    ),
    "twenty_create_company": _integration_definition(
        name="twenty_create_company",
        description="Create a Twenty CRM company record (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.create_company",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("create company", "add company", "new company"),
        requires_approval=True,
    ),
    "twenty_update_company": _integration_definition(
        name="twenty_update_company",
        description="Update a Twenty CRM company record (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.update_company",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("update company", "edit company", "update account"),
        requires_approval=True,
    ),
    "twenty_search_opportunities": _integration_definition(
        name="twenty_search_opportunities",
        description="Search Twenty CRM opportunities/deals by query/filter.",
        category="crm",
        provider="twenty",
        implementation="twenty.search_opportunities",
        permissions=(Permission.READ_CRM,),
        execution_capability=None,
        keywords=("opportunities", "deals", "pipeline", "search deals"),
    ),
    "twenty_create_opportunity": _integration_definition(
        name="twenty_create_opportunity",
        description="Create a Twenty CRM opportunity (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.create_opportunity",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("create opportunity", "add deal", "new opportunity"),
        requires_approval=True,
    ),
    "twenty_update_opportunity": _integration_definition(
        name="twenty_update_opportunity",
        description="Update a Twenty CRM opportunity (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.update_opportunity",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("update opportunity", "update deal", "move deal"),
        requires_approval=True,
    ),
    "twenty_create_task": _integration_definition(
        name="twenty_create_task",
        description="Create a Twenty CRM task (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.create_task",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("create task", "add task", "new task", "log task"),
        requires_approval=True,
    ),
    "twenty_update_task": _integration_definition(
        name="twenty_update_task",
        description="Update a Twenty CRM task (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.update_task",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("update task", "complete task", "mark task done"),
        requires_approval=True,
    ),
    "twenty_list_tasks": _integration_definition(
        name="twenty_list_tasks",
        description="List Twenty CRM tasks with optional query/filter.",
        category="crm",
        provider="twenty",
        implementation="twenty.list_tasks",
        permissions=(Permission.READ_CRM,),
        execution_capability=None,
        keywords=("list tasks", "tasks", "my tasks", "crm tasks"),
    ),
    "twenty_get_task": _integration_definition(
        name="twenty_get_task",
        description="Fetch one Twenty CRM task by id.",
        category="crm",
        provider="twenty",
        implementation="twenty.get_task",
        permissions=(Permission.READ_CRM,),
        execution_capability=None,
        keywords=("get task", "task by id", "task details"),
    ),
    "twenty_create_note": _integration_definition(
        name="twenty_create_note",
        description="Create a Twenty CRM note (requires WRITE_CRM + approval).",
        category="crm",
        provider="twenty",
        implementation="twenty.create_note",
        permissions=(Permission.WRITE_CRM,),
        execution_capability=None,
        keywords=("create note", "add note", "log note"),
        requires_approval=True,
    ),
    "twenty_get_record": _integration_definition(
        name="twenty_get_record",
        description="Fetch a single Twenty CRM record by object slug + id.",
        category="crm",
        provider="twenty",
        implementation="twenty.get_record",
        permissions=(Permission.READ_CRM,),
        execution_capability=None,
        keywords=("get record", "fetch record", "record by id", "read record"),
    ),
}
BUILTIN_CAPABILITIES.update(_TWENTY_CAPABILITIES)

#: n8n workflow-automation capabilities (integration-backed through
#: N8NConnector). Reads require READ_AUTOMATION; running a workflow
#: requires EXECUTE_AUTOMATION (dangerous, never implicit) and an
#: approved workflow context.
_N8N_CAPABILITIES: dict[str, CapabilityDefinition] = {
    "n8n_health": _integration_definition(
        name="n8n_health",
        description="Report n8n configuration readiness.",
        category="automation",
        provider="n8n",
        implementation="n8n.health",
        permissions=(Permission.READ_AUTOMATION,),
        execution_capability=None,
        keywords=("n8n", "workflow", "automation", "workflow health"),
    ),
    "n8n_list_workflows": _integration_definition(
        name="n8n_list_workflows",
        description="List n8n workflows with optional filters.",
        category="automation",
        provider="n8n",
        implementation="n8n.list_workflows",
        permissions=(Permission.READ_AUTOMATION,),
        execution_capability=None,
        keywords=("n8n workflows", "list workflows", "automation workflows", "workflow list"),
    ),
    "n8n_get_workflow": _integration_definition(
        name="n8n_get_workflow",
        description="Fetch one n8n workflow by id.",
        category="automation",
        provider="n8n",
        implementation="n8n.get_workflow",
        permissions=(Permission.READ_AUTOMATION,),
        execution_capability=None,
        keywords=("n8n workflow by id", "get workflow", "workflow details"),
    ),
    "n8n_run_workflow": _integration_definition(
        name="n8n_run_workflow",
        description=(
            "Trigger an n8n workflow execution and return its result "
            "(requires EXECUTE_AUTOMATION + approval)."
        ),
        category="automation",
        provider="n8n",
        implementation="n8n.run_workflow",
        permissions=(Permission.EXECUTE_AUTOMATION,),
        execution_capability=None,
        keywords=("run workflow", "trigger workflow", "execute workflow", "start automation"),
        requires_approval=True,
    ),
    "n8n_get_execution": _integration_definition(
        name="n8n_get_execution",
        description="Fetch one n8n workflow execution by id.",
        category="automation",
        provider="n8n",
        implementation="n8n.get_execution",
        permissions=(Permission.READ_AUTOMATION,),
        execution_capability=None,
        keywords=("execution result", "workflow execution", "get execution"),
    ),
}
BUILTIN_CAPABILITIES.update(_N8N_CAPABILITIES)

#: Social media capabilities (contract-only until a provider is wired).
#: Every capability is registered so resolution finds it; availability is
#: honestly Not Configured. Create/publish actions additionally require
#: PUBLISH_SOCIAL and an approved workflow context.
def _social_definition(
    name: str,
    description: str,
    provider: str,
    action: str,
    keywords: tuple[str, ...],
    *,
    requires_approval: bool = False,
) -> CapabilityDefinition:
    read_only = action in ("get_post", "get_insights", "get_analytics")
    return _integration_definition(
        name=name,
        description=description,
        category="social",
        provider="social",
        implementation=f"social.{provider}.{action}",
        permissions=(Permission.READ_SOCIAL if read_only else Permission.PUBLISH_SOCIAL,),
        execution_capability=None,
        keywords=keywords,
        requires_approval=requires_approval,
    )


def _social_definitions(
    provider: str,
    display_name: str,
) -> dict[str, CapabilityDefinition]:
    """Return the four standard capabilities for one social provider."""
    short = provider
    keywords = {
        "meta": {
            "create_post": ("draft instagram post", "draft facebook post", "draft meta post"),
            "publish_post": ("post to instagram", "post on facebook", "publish to facebook", "publish to instagram"),
            "get_post": ("get instagram post", "get facebook post", "get meta post"),
            "get_insights": ("instagram insights", "facebook insights", "meta insights", "social insights"),
        },
        "linkedin": {
            "create_post": ("draft linkedin post", "draft linkedin update"),
            "publish_post": ("post to linkedin", "publish linkedin", "linkedin post"),
            "get_post": ("get linkedin post",),
            "get_analytics": ("linkedin analytics", "linkedin impressions", "linkedin engagement"),
        },
        "x": {
            "create_post": ("draft x post", "draft tweet", "draft twitter post"),
            "publish_post": ("post to x", "tweet", "publish tweet", "publish to x"),
            "get_post": ("get tweet", "get x post", "get twitter post"),
            "get_analytics": ("x analytics", "tweet analytics", "twitter analytics"),
        },
        "reddit": {
            "create_post": ("draft reddit post", "draft reddit submission"),
            "publish_post": ("post to reddit", "publish reddit", "reddit post"),
            "get_post": ("get reddit post",),
            "get_analytics": ("reddit analytics", "reddit engagement", "reddit insights"),
        },
    }[provider]
    action_names = (
        ("create_post", "publish_post", "get_post", "get_insights")
        if provider == "meta"
        else ("create_post", "publish_post", "get_post", "get_analytics")
    )
    definitions: dict[str, CapabilityDefinition] = {}
    for action in action_names:
        read_only = action in ("get_post", "get_insights", "get_analytics")
        name = f"social_{short}_{action}"
        action_label = action.replace("_", " ")
        definitions[name] = _social_definition(
            name=name,
            description=(
                f"{action_label.title()} on {display_name} "
                f"(provider not configured yet)."
            ),
            provider=short,
            action=action,
            keywords=keywords[action],
            requires_approval=not read_only,
        )
    return definitions


BUILTIN_CAPABILITIES.update(
    {
        **_social_definitions("meta", "Meta/Facebook/Instagram"),
        **_social_definitions("linkedin", "LinkedIn"),
        **_social_definitions("x", "X (Twitter)"),
        **_social_definitions("reddit", "Reddit"),
    }
)

#: Direct social provider capabilities — wired to the REAL connector
#: implementations (LinkedInConnector, TwitterConnector, RedditConnector)
#: instead of the abstract SocialConnector. These are executable when the
#: provider credentials are configured.
_LINKEDIN_DIRECT: dict[str, CapabilityDefinition] = {
    "linkedin_get_organization": _integration_definition(
        name="linkedin_get_organization",
        description="Fetch authenticated LinkedIn organization profile.",
        category="social",
        provider="linkedin",
        implementation="linkedin.get_organization",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("linkedin organization", "linkedin company", "linkedin profile"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "url": {"type": "string"},
            },
        },
    ),
    "linkedin_create_post": _integration_definition(
        name="linkedin_create_post",
        description="Create a LinkedIn text post (requires PUBLISH_SOCIAL + approval).",
        category="social",
        provider="linkedin",
        implementation="linkedin.create_text_post",
        permissions=(Permission.PUBLISH_SOCIAL,),
        execution_capability=None,
        keywords=("linkedin post", "post to linkedin", "linkedin update"),
        requires_approval=True,
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Post content text"},
            },
            "required": ["text"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    ),
    "linkedin_get_post": _integration_definition(
        name="linkedin_get_post",
        description="Fetch a LinkedIn post by ID.",
        category="social",
        provider="linkedin",
        implementation="linkedin.get_post",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("get linkedin post", "linkedin post details"),
        input_schema={
            "type": "object",
            "properties": {
                "post_id": {"type": "string", "description": "LinkedIn post URN or ID"},
            },
            "required": ["post_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "text": {"type": "string"},
                "created_at": {"type": "string"},
            },
        },
    ),
    "linkedin_get_stats": _integration_definition(
        name="linkedin_get_stats",
        description="Get LinkedIn organization analytics and statistics.",
        category="analytics",
        provider="linkedin",
        implementation="linkedin.get_organization_stats",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("linkedin stats", "linkedin analytics", "linkedin impressions"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "impressions": {"type": "integer"},
                "clicks": {"type": "integer"},
                "engagement_rate": {"type": "number"},
            },
        },
    ),
    "linkedin_get_post_analytics": _integration_definition(
        name="linkedin_get_post_analytics",
        description="Get analytics for a specific LinkedIn post.",
        category="analytics",
        provider="linkedin",
        implementation="linkedin.get_post_analytics",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("linkedin post analytics", "linkedin post metrics", "linkedin engagement"),
        input_schema={
            "type": "object",
            "properties": {
                "post_id": {"type": "string", "description": "LinkedIn post URN or ID"},
            },
            "required": ["post_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "impressions": {"type": "integer"},
                "clicks": {"type": "integer"},
                "reactions": {"type": "integer"},
                "comments": {"type": "integer"},
            },
        },
    ),
}
BUILTIN_CAPABILITIES.update(_LINKEDIN_DIRECT)

_TWITTER_DIRECT: dict[str, CapabilityDefinition] = {
    "twitter_get_me": _integration_definition(
        name="twitter_get_me",
        description="Fetch the authenticated X/Twitter user profile.",
        category="social",
        provider="twitter",
        implementation="twitter.get_me",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("twitter profile", "x profile", "twitter account", "x account"),
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {"id": {"type": "string"}, "username": {"type": "string"}, "name": {"type": "string"}}},
    ),
    "twitter_create_post": _integration_definition(
        name="twitter_create_post",
        description="Create a tweet / X post (requires PUBLISH_SOCIAL + approval).",
        category="social",
        provider="twitter",
        implementation="twitter.create_tweet",
        permissions=(Permission.PUBLISH_SOCIAL,),
        execution_capability=None,
        keywords=("tweet", "post to x", "create tweet", "twitter post"),
        requires_approval=True,
        input_schema={"type": "object", "properties": {"text": {"type": "string", "description": "Tweet content"}}, "required": ["text"]},
        output_schema={"type": "object", "properties": {"tweet_id": {"type": "string"}, "status": {"type": "string"}}},
    ),
    "twitter_get_post": _integration_definition(
        name="twitter_get_post",
        description="Fetch a tweet by ID with metrics.",
        category="social",
        provider="twitter",
        implementation="twitter.get_tweet",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("get tweet", "get x post", "tweet details"),
        input_schema={"type": "object", "properties": {"tweet_id": {"type": "string", "description": "Tweet ID"}}, "required": ["tweet_id"]},
        output_schema={"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}, "metrics": {"type": "object"}}},
    ),
    "twitter_get_user_posts": _integration_definition(
        name="twitter_get_user_posts",
        description="List recent tweets from a user.",
        category="social",
        provider="twitter",
        implementation="twitter.get_user_tweets",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("twitter timeline", "user tweets", "x posts"),
        input_schema={"type": "object", "properties": {"user_id": {"type": "string", "description": "X/Twitter user ID"}, "max_results": {"type": "integer", "default": 10}}, "required": ["user_id"]},
        output_schema={"type": "object", "properties": {"tweets": {"type": "array", "items": {"type": "object"}}}},
    ),
    "twitter_get_post_metrics": _integration_definition(
        name="twitter_get_post_metrics",
        description="Get aggregated analytics for tweets.",
        category="analytics",
        provider="twitter",
        implementation="twitter.get_tweet_metrics",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("twitter analytics", "tweet metrics", "x analytics", "tweet engagement"),
        input_schema={"type": "object", "properties": {"tweet_ids": {"type": "array", "items": {"type": "string"}, "description": "List of tweet IDs"}}, "required": ["tweet_ids"]},
        output_schema={"type": "object", "properties": {"metrics": {"type": "object"}}},
    ),
}
BUILTIN_CAPABILITIES.update(_TWITTER_DIRECT)

_REDDIT_DIRECT: dict[str, CapabilityDefinition] = {
    "reddit_get_me": _integration_definition(
        name="reddit_get_me",
        description="Fetch the authenticated Reddit user profile.",
        category="social",
        provider="reddit",
        implementation="reddit.get_me",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("reddit profile", "reddit account", "reddit me"),
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {"name": {"type": "string"}, "link_karma": {"type": "integer"}, "comment_karma": {"type": "integer"}}},
    ),
    "reddit_list_subreddits": _integration_definition(
        name="reddit_list_subreddits",
        description="List subreddits the user is subscribed to.",
        category="social",
        provider="reddit",
        implementation="reddit.list_subreddits",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("reddit subreddits", "subscribed subreddits", "my subreddits"),
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {"subreddits": {"type": "array", "items": {"type": "object"}}}},
    ),
    "reddit_get_post": _integration_definition(
        name="reddit_get_post",
        description="Fetch a Reddit post by ID.",
        category="social",
        provider="reddit",
        implementation="reddit.get_post",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("get reddit post", "reddit post details"),
        input_schema={"type": "object", "properties": {"post_id": {"type": "string", "description": "Reddit post ID or full URL"}}, "required": ["post_id"]},
        output_schema={"type": "object", "properties": {"title": {"type": "string"}, "selftext": {"type": "string"}, "subreddit": {"type": "string"}, "score": {"type": "integer"}}},
    ),
    "reddit_get_subreddit": _integration_definition(
        name="reddit_get_subreddit",
        description="Get information about a subreddit.",
        category="social",
        provider="reddit",
        implementation="reddit.get_subreddit",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("subreddit info", "subreddit details", "subreddit stats"),
        input_schema={"type": "object", "properties": {"subreddit": {"type": "string", "description": "Subreddit name"}}, "required": ["subreddit"]},
        output_schema={"type": "object", "properties": {"display_name": {"type": "string"}, "subscribers": {"type": "integer"}, "description": {"type": "string"}}},
    ),
    "reddit_submit_post": _integration_definition(
        name="reddit_submit_post",
        description="Submit a post to a subreddit (requires PUBLISH_SOCIAL + approval).",
        category="social",
        provider="reddit",
        implementation="reddit.submit_post",
        permissions=(Permission.PUBLISH_SOCIAL,),
        execution_capability=None,
        keywords=("reddit post", "post to reddit", "submit reddit"),
        requires_approval=True,
        input_schema={"type": "object", "properties": {"subreddit": {"type": "string"}, "title": {"type": "string"}, "text": {"type": "string"}}, "required": ["subreddit", "title"]},
        output_schema={"type": "object", "properties": {"post_id": {"type": "string"}, "url": {"type": "string"}}},
    ),
    "reddit_submit_comment": _integration_definition(
        name="reddit_submit_comment",
        description="Comment on a Reddit post (requires PUBLISH_SOCIAL + approval).",
        category="social",
        provider="reddit",
        implementation="reddit.submit_comment",
        permissions=(Permission.PUBLISH_SOCIAL,),
        execution_capability=None,
        keywords=("reddit comment", "comment on reddit", "reply to reddit"),
        requires_approval=True,
        input_schema={"type": "object", "properties": {"post_id": {"type": "string", "description": "Reddit post ID"}, "text": {"type": "string", "description": "Comment text"}}, "required": ["post_id", "text"]},
        output_schema={"type": "object", "properties": {"comment_id": {"type": "string"}, "status": {"type": "string"}}},
    ),
}
BUILTIN_CAPABILITIES.update(_REDDIT_DIRECT)

#: ----------------------------------------------------------------------
#: External capability adapters — WhatsApp, Memory, Web/SEO, Search
#: ----------------------------------------------------------------------

_OPENWA_CAPABILITIES: dict[str, CapabilityDefinition] = {
    "whatsapp_send_message": _integration_definition(
        name="whatsapp_send_message",
        description="Send a WhatsApp text message via OpenWA.",
        category="communication",
        provider="openwa",
        implementation="whatsapp.send_message",
        permissions=(Permission.PUBLISH_SOCIAL,),
        execution_capability=None,
        keywords=("whatsapp", "send message", "send whatsapp", "whatsapp text"),
        requires_approval=True,
        input_schema={"type": "object", "properties": {"to_number": {"type": "string", "description": "Recipient phone number"}, "body": {"type": "string", "description": "Message text"}}, "required": ["to_number", "body"]},
        output_schema={"type": "object", "properties": {"success": {"type": "boolean"}, "message_id": {"type": "string"}}},
    ),
    "whatsapp_send_media": _integration_definition(
        name="whatsapp_send_media",
        description="Send a WhatsApp media message (image, video, document) via OpenWA.",
        category="communication",
        provider="openwa",
        implementation="whatsapp.send_media",
        permissions=(Permission.PUBLISH_SOCIAL,),
        execution_capability=None,
        keywords=("whatsapp media", "send image whatsapp", "send video whatsapp", "send document whatsapp"),
        requires_approval=True,
        input_schema={"type": "object", "properties": {"to_number": {"type": "string"}, "media_url": {"type": "string"}, "caption": {"type": "string"}}, "required": ["to_number", "media_url"]},
        output_schema={"type": "object", "properties": {"success": {"type": "boolean"}, "message_id": {"type": "string"}}},
    ),
    "whatsapp_receive_message": _integration_definition(
        name="whatsapp_receive_message",
        description="Receive/poll recent WhatsApp messages via OpenWA.",
        category="communication",
        provider="openwa",
        implementation="whatsapp.receive_message",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("receive whatsapp", "whatsapp inbox", "whatsapp messages"),
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {"messages": {"type": "array", "items": {"type": "object"}}, "count": {"type": "integer"}}},
    ),
    "whatsapp_list_sessions": _integration_definition(
        name="whatsapp_list_sessions",
        description="List active WhatsApp sessions in OpenWA.",
        category="communication",
        provider="openwa",
        implementation="whatsapp.list_sessions",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("whatsapp sessions", "whatsapp status"),
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {"sessions": {"type": "array"}, "count": {"type": "integer"}}},
    ),
    "whatsapp_session_status": _integration_definition(
        name="whatsapp_session_status",
        description="Get the status of a specific WhatsApp session.",
        category="communication",
        provider="openwa",
        implementation="whatsapp.session_status",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("whatsapp session status", "whatsapp connected"),
        input_schema={"type": "object", "properties": {"session_id": {"type": "string"}}, "required": []},
        output_schema={"type": "object", "properties": {"session_id": {"type": "string"}, "status": {"type": "string"}}},
    ),
}
BUILTIN_CAPABILITIES.update(_OPENWA_CAPABILITIES)

_MEMORY_CAPABILITIES: dict[str, CapabilityDefinition] = {
    "memory_remember": _integration_definition(
        name="memory_remember",
        description="Store a fact, preference, or decision in long-term memory.",
        category="memory",
        provider="memory",
        implementation="memory.remember",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("remember", "store memory", "save to memory", "remember this"),
        input_schema={"type": "object", "properties": {"content": {"type": "string", "description": "Memory content"}, "entity": {"type": "string"}, "memory_type": {"type": "string", "enum": ["fact", "preference", "decision", "conversation", "task", "event", "knowledge", "outcome"]}}, "required": ["content"]},
        output_schema={"type": "object", "properties": {"success": {"type": "boolean"}, "memory_id": {"type": "string"}}},
    ),
    "memory_recall": _integration_definition(
        name="memory_recall",
        description="Recall relevant memories for a given query.",
        category="memory",
        provider="memory",
        implementation="memory.recall",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("recall", "what did we discuss", "remember earlier", "recall memory"),
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "entity": {"type": "string"}, "memory_type": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]},
        output_schema={"type": "object", "properties": {"memories": {"type": "array", "items": {"type": "object"}}, "count": {"type": "integer"}}},
    ),
    "memory_search": _integration_definition(
        name="memory_search",
        description="Semantic search across all stored memories.",
        category="memory",
        provider="memory",
        implementation="memory.search",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("search memory", "find in memory", "memory search"),
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]},
        output_schema={"type": "object", "properties": {"results": {"type": "array", "items": {"type": "object"}}, "count": {"type": "integer"}}},
    ),
    "memory_forget": _integration_definition(
        name="memory_forget",
        description="Delete a specific memory record.",
        category="memory",
        provider="memory",
        implementation="memory.forget",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("forget", "delete memory", "remove memory"),
        input_schema={"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]},
        output_schema={"type": "object", "properties": {"success": {"type": "boolean"}}},
    ),
    "memory_health": _integration_definition(
        name="memory_health",
        description="Check memory service health status.",
        category="memory",
        provider="memory",
        implementation="memory.health",
        permissions=(Permission.READ_SOCIAL,),
        execution_capability=None,
        keywords=("memory health", "memory status"),
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {"status": {"type": "string"}, "message": {"type": "string"}}},
    ),
}
BUILTIN_CAPABILITIES.update(_MEMORY_CAPABILITIES)

_WEB_SEO_CAPABILITIES: dict[str, CapabilityDefinition] = {
    "web_crawl_url": _integration_definition(
        name="web_crawl_url",
        description="Crawl a URL and extract content using Crawl4AI.",
        category="web",
        provider="crawl4ai",
        implementation="web.crawl_url",
        permissions=(Permission.READ_WEBSITE,),
        execution_capability=None,
        keywords=("crawl url", "scrape page", "fetch page content", "web crawl"),
        input_schema={"type": "object", "properties": {"url": {"type": "string", "description": "URL to crawl"}}, "required": ["url"]},
        output_schema={"type": "object", "properties": {"url": {"type": "string"}, "title": {"type": "string"}, "markdown": {"type": "string"}, "success": {"type": "boolean"}}},
    ),
    "web_analyze_page": _integration_definition(
        name="web_analyze_page",
        description="Analyze a web page for basic metrics and content quality.",
        category="web",
        provider="crawl4ai",
        implementation="web.analyze_page",
        permissions=(Permission.READ_WEBSITE,),
        execution_capability=None,
        keywords=("analyze page", "page analysis", "web page metrics"),
        input_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        output_schema={"type": "object", "properties": {"url": {"type": "string"}, "title": {"type": "string"}, "word_count": {"type": "integer"}, "links_count": {"type": "integer"}}},
    ),
    "web_seo_audit": _integration_definition(
        name="web_seo_audit",
        description="Run a basic SEO audit on a web page.",
        category="seo",
        provider="crawl4ai",
        implementation="web.seo_audit",
        permissions=(Permission.READ_WEBSITE,),
        execution_capability=None,
        keywords=("seo audit", "seo check", "search engine optimization", "seo score"),
        input_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        output_schema={"type": "object", "properties": {"url": {"type": "string"}, "title": {"type": "string"}, "score": {"type": "integer"}, "issues": {"type": "array", "items": {"type": "string"}}}},
    ),
    "web_extract_content": _integration_definition(
        name="web_extract_content",
        description="Extract clean text content from a web page.",
        category="web",
        provider="crawl4ai",
        implementation="web.extract_content",
        permissions=(Permission.READ_WEBSITE,),
        execution_capability=None,
        keywords=("extract content", "get page text", "web content extraction"),
        input_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        output_schema={"type": "object", "properties": {"url": {"type": "string"}, "content": {"type": "string"}, "title": {"type": "string"}}},
    ),
}
BUILTIN_CAPABILITIES.update(_WEB_SEO_CAPABILITIES)

_SEARCH_CAPABILITIES: dict[str, CapabilityDefinition] = {
    "search_web": _integration_definition(
        name="search_web",
        description="Search the web using SearXNG privacy-respecting search.",
        category="search",
        provider="searxng",
        implementation="search.web",
        permissions=(Permission.READ_WEBSITE,),
        execution_capability=None,
        keywords=("search web", "web search", "search the internet", "google search"),
        input_schema={"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}, "max_results": {"type": "integer", "default": 10}}, "required": ["query"]},
        output_schema={"type": "object", "properties": {"query": {"type": "string"}, "results": {"type": "array", "items": {"type": "object"}}, "total": {"type": "integer"}}},
    ),
    "search_news": _integration_definition(
        name="search_news",
        description="Search for recent news using SearXNG.",
        category="search",
        provider="searxng",
        implementation="search.news",
        permissions=(Permission.READ_WEBSITE,),
        execution_capability=None,
        keywords=("search news", "news search", "find news", "latest news"),
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 10}}, "required": ["query"]},
        output_schema={"type": "object", "properties": {"query": {"type": "string"}, "results": {"type": "array"}, "total": {"type": "integer"}}},
    ),
}
BUILTIN_CAPABILITIES.update(_SEARCH_CAPABILITIES)
