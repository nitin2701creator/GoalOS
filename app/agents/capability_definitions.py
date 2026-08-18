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
