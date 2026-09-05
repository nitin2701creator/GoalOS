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
    # ------------------------------------------------------------------
    # LinkedIn skills — Phase 1 (no credentials required)
    # ------------------------------------------------------------------
    "linkedin_post_writer": SkillDefinition(
        name="linkedin_post_writer",
        description="Generate a LinkedIn post draft from a topic, audience, and goal.",
        instructions=(
            "Write a LinkedIn post for the given topic and audience. "
            "Start with a strong hook (first line that stops the scroll). "
            "Use short paragraphs, line breaks for readability, and a clear "
            "call to action. The tone should be professional yet conversational. "
            "Do not use hashtags in the body — they go at the end. "
            "Return structured output with the hook, body, hashtags, and CTA."
        ),
        input_schema={
            "topic": "string",
            "audience": "string",
            "goal": "string",
            "tone": "string",
        },
        output_schema={
            "hook": "string",
            "body": "string",
            "hashtags": ["string"],
            "cta": "string",
            "full_post": "string",
        },
        permissions=(Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL),
    ),
    "linkedin_comment_drafter": SkillDefinition(
        name="linkedin_comment_drafter",
        description="Draft an engaging comment on a LinkedIn post.",
        instructions=(
            "Read the provided LinkedIn post and draft a thoughtful comment. "
            "The comment should add value: share an insight, ask a question, "
            "or reinforce the author's point. Avoid generic praise like "
            "'Great post!'. Keep it concise (1-3 sentences max). "
            "Match the tone of the original post."
        ),
        input_schema={
            "post_text": "string",
            "context": "string",
            "persona": "string",
        },
        output_schema={
            "comment": "string",
            "tone": "string",
            "rationale": "string",
        },
        permissions=(Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL),
    ),
    "linkedin_reply_handler": SkillDefinition(
        name="linkedin_reply_handler",
        description="Draft a reply to a LinkedIn comment or message.",
        instructions=(
            "Read the incoming LinkedIn comment or message and draft a reply. "
            "Acknowledge the commenter's point, add value, and maintain a "
            "professional tone. If the comment is negative, respond graciously "
            "without being defensive. Keep replies concise (1-4 sentences). "
            "Do not argue or be dismissive."
        ),
        input_schema={
            "comment_text": "string",
            "original_post": "string",
            "context": "string",
        },
        output_schema={
            "reply": "string",
            "tone": "string",
            "escalation_needed": "boolean",
        },
        permissions=(Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL),
    ),
    "linkedin_humanizer": SkillDefinition(
        name="linkedin_humanizer",
        description="Rewrite AI-generated content to sound more natural and human.",
        instructions=(
            "Rewrite the provided text to sound more human and authentic. "
            "Remove corporate jargon, filler phrases, and robotic patterns. "
            "Add natural conversational elements: contractions, personal touch, "
            "varied sentence length, rhetorical questions. Preserve the core "
            "message while making it feel like a real person wrote it. "
            "Avoid: 'In today's world', 'It is important to note', 'Leverage', "
            "'Synergy', excessive exclamation marks."
        ),
        input_schema={
            "text": "string",
            "style": "string",
        },
        output_schema={
            "humanized_text": "string",
            "changes_made": ["string"],
            "naturalness_score": "number",
        },
        permissions=(Permission.READ_SOCIAL,),
    ),
    "linkedin_hook_extractor": SkillDefinition(
        name="linkedin_hook_extractor",
        description="Extract and analyze hooks from LinkedIn content.",
        instructions=(
            "Analyze the provided LinkedIn content to extract the opening hook "
            "patterns used. Identify: the hook type (question, statistic, story, "
            "bold claim, contrarian take, personal anecdote), why it works, "
            "and the psychological trigger it uses. Also extract hooks from "
            "any additional examples provided. Rank hooks by likely engagement."
        ),
        input_schema={
            "content": "string",
            "additional_examples": ["string"],
        },
        output_schema={
            "hooks": [{"text": "string", "type": "string", "trigger": "string", "strength": "number"}],
            "ranking": ["string"],
            "recommendations": ["string"],
        },
        permissions=(Permission.READ_SOCIAL,),
    ),
    "linkedin_content_planner": SkillDefinition(
        name="linkedin_content_planner",
        description="Create a structured LinkedIn content calendar from business goals.",
        instructions=(
            "Create a weekly LinkedIn content plan based on the provided business "
            "goals, topics, and audience. Use a balanced mix of content types: "
            "thought leadership (40%), educational (25%), personal/story (20%), "
            "promotional (15%). Each day should have: topic, angle, content type, "
            "hook preview, and optimal posting time. Avoid repeating topics within "
            "the same week."
        ),
        input_schema={
            "business_goals": ["string"],
            "topics": ["string"],
            "audience": "string",
            "week_start": "string",
        },
        output_schema={
            "calendar": [{"day": "string", "topic": "string", "type": "string", "hook": "string", "time": "string"}],
            "content_mix": {"thought_leadership": "number", "educational": "number", "personal": "number", "promotional": "number"},
        },
        permissions=(Permission.READ_SOCIAL,),
    ),
    "linkedin_repurposer": SkillDefinition(
        name="linkedin_repurposer",
        description="Transform content into LinkedIn-optimized format.",
        instructions=(
            "Transform the provided source content into a LinkedIn-ready format. "
            "Support these transformations: blog_to_post (long article to concise "
            "post), video_to_post (video description to text post), "
            "thread_to_single (multi-part to one strong post), "
            "report_to_post (data/report to engaging summary). "
            "Preserve key insights while optimizing for LinkedIn's format: "
            "short paragraphs, line breaks, hook-first structure."
        ),
        input_schema={
            "source_content": "string",
            "transformation_type": "string",
            "target_audience": "string",
        },
        output_schema={
            "linkedin_post": "string",
            "hook": "string",
            "key_points": ["string"],
            "source_type": "string",
        },
        permissions=(Permission.READ_SOCIAL,),
    ),
    "linkedin_post_audit": SkillDefinition(
        name="linkedin_post_audit",
        description="Analyze a LinkedIn post for quality, engagement potential, and improvements.",
        instructions=(
            "Audit the provided LinkedIn post across multiple dimensions: "
            "hook strength (does the first line stop the scroll?), "
            "readability (short paragraphs, line breaks, no walls of text), "
            "CTA clarity (is there a clear call to action?), "
            "emotional pull (does it evoke a response?), "
            "authenticity (does it sound human or corporate?), "
            "value density (is every sentence earning its place?). "
            "Provide a numerical score (0-100) and specific improvement suggestions."
        ),
        input_schema={
            "post_text": "string",
            "goal": "string",
        },
        output_schema={
            "overall_score": "number",
            "hook_score": "number",
            "readability_score": "number",
            "cta_score": "number",
            "emotional_score": "number",
            "authenticity_score": "number",
            "improvements": ["string"],
            "strengths": ["string"],
        },
        permissions=(Permission.READ_SOCIAL,),
    ),
}
