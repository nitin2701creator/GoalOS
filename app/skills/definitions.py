"""Formal skill definitions for GoalOS.

A :class:`SkillDefinition` is the reusable, validated contract behind a
skill: name, description, instructions, required tools, input/output
schemas, permissions, version, and enabled state. Skills are reusable
across agents — one ``keyword_research`` skill definition can be attached
to the SEO agent, the marketing manager agent, and the growth agent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.permissions import Permission


class SkillDefinition(BaseModel):
    """A validated, reusable skill contract.

    Attributes:
        name: Unique skill name.
        description: Human-readable summary of the skill.
        instructions: Deterministic instructions for the skill.
        required_tools: Tool names the skill needs.
        input_schema: Structured input contract for execution.
        output_schema: Structured output contract for results.
        permissions: Permissions the skill requires from its agent.
        version: Skill definition version.
        enabled: Whether the skill may be attached to new agents.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    instructions: str = ""
    required_tools: tuple[str, ...] = ()
    required_integrations: tuple[str, ...] = ()
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: tuple[Permission, ...] = ()
    version: str = "1.0"
    enabled: bool = True


#: Built-in skill definitions keyed by skill name. The factory reuses these
#: when creating missing skills; agents attach them by name so one definition
#: serves any number of agents.
BUILTIN_SKILLS: dict[str, SkillDefinition] = {
    "calculation": SkillDefinition(
        name="calculation",
        description="Perform deterministic arithmetic on numeric inputs.",
        instructions=(
            "Evaluate the requested arithmetic operation (add, subtract, "
            "multiply, divide) over the numeric inputs a and b."
        ),
        input_schema={"a": "number", "b": "number", "operation": "string"},
        output_schema={"result": "number"},
        permissions=(Permission.EXECUTE_CODE,),
    ),
    "keyword_research": SkillDefinition(
        name="keyword_research",
        description="Derive keyword candidates for a topic using real web search.",
        instructions=(
            "Search the web for the topic and return the top keyword phrases "
            "from real search results."
        ),
        required_integrations=("web",),
        input_schema={"topic": "string"},
        output_schema={"keywords": ["string"]},
        permissions=(Permission.READ_WEBSITE,),
    ),
    "website_analysis": SkillDefinition(
        name="website_analysis",
        description="Crawl and analyze a website's SEO signals.",
        instructions=(
            "Crawl the target website and return its technical SEO findings, "
            "titles, descriptions, and word counts."
        ),
        required_integrations=("web", "website"),
        input_schema={"url": "string"},
        output_schema={"findings": ["string"], "score": "number"},
        permissions=(Permission.READ_WEBSITE,),
    ),
    "content_analysis": SkillDefinition(
        name="content_analysis",
        description="Summarize content length and structure deterministically.",
        instructions=(
            "Analyze the supplied content and return structural metrics."
        ),
        input_schema={"content": "string"},
        output_schema={"word_count": "number", "summary": "string"},
        permissions=(Permission.READ_WEBSITE, Permission.READ_FILES),
    ),
    "web_research": SkillDefinition(
        name="web_research",
        description="Research a query using real web search results.",
        instructions=(
            "Search the web for the query and return the top structured "
            "findings from real results."
        ),
        required_integrations=("web",),
        input_schema={"query": "string"},
        output_schema={"findings": ["string"]},
        permissions=(Permission.READ_WEBSITE,),
    ),
    "company_discovery": SkillDefinition(
        name="company_discovery",
        description="Discover companies matching an industry and region via web search.",
        instructions=(
            "Search the web for companies in the industry and region and "
            "return the top candidates."
        ),
        required_integrations=("web",),
        input_schema={"industry": "string", "region": "string"},
        output_schema={"companies": ["string"]},
        permissions=(Permission.READ_WEBSITE,),
    ),
    "contact_extraction": SkillDefinition(
        name="contact_extraction",
        description="Extract contact details from provided text.",
        instructions=(
            "Return deterministic contact candidates found in the supplied text."
        ),
        required_integrations=("web", "gmail"),
        input_schema={"text": "string"},
        output_schema={"contacts": ["string"]},
        permissions=(Permission.READ_WEBSITE, Permission.READ_EMAIL),
    ),
    "lead_qualification": SkillDefinition(
        name="lead_qualification",
        description="Qualify leads against deterministic criteria.",
        instructions=(
            "Score the supplied lead against the qualification criteria."
        ),
        required_integrations=("google_analytics",),
        input_schema={"lead": "string", "criteria": ["string"]},
        output_schema={"score": "number", "qualified": "boolean"},
        permissions=(Permission.READ_ANALYTICS,),
    ),
    "email_drafting": SkillDefinition(
        name="email_drafting",
        description="Draft a professional email from an outline.",
        instructions=(
            "Compose a professional email from the given recipient, subject, "
            "and body outline."
        ),
        required_integrations=("gmail",),
        input_schema={"recipient": "string", "subject": "string", "outline": "string"},
        output_schema={"subject": "string", "body": "string"},
        permissions=(Permission.SEND_EMAIL,),
    ),
    "sales_analysis": SkillDefinition(
        name="sales_analysis",
        description="Analyze store sales and traffic from WooCommerce and GA4.",
        instructions=(
            "Read WooCommerce products/orders and GA4 analytics reports and "
            "return a structured sales summary."
        ),
        required_integrations=("woocommerce", "google_analytics"),
        input_schema={"topic": "string", "start_date": "string", "end_date": "string"},
        output_schema={"summary": "string", "products": ["string"], "analytics": "object"},
        permissions=(Permission.READ_WEBSITE, Permission.READ_ANALYTICS),
    ),
}
