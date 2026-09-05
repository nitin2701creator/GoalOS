"""LinkedIn Skills API endpoints for GoalOS.

8 no-credential LinkedIn capabilities exposed as REST endpoints.
No LinkedIn API calls are made. No credentials required.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Any

from app.services.linkedin_skills import (
    audit_post,
    draft_comment,
    draft_reply,
    extract_hooks,
    generate_post_draft,
    humanize_text,
    plan_content,
    repurpose_content,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class DraftPostRequest(BaseModel):
    topic: str = Field(min_length=1, description="Post topic or subject")
    audience: str = Field(default="", description="Target audience")
    goal: str = Field(default="", description="Post goal")
    tone: str = Field(default="", description="Desired tone")


class DraftCommentRequest(BaseModel):
    post_text: str = Field(min_length=1, description="The LinkedIn post to comment on")
    context: str = Field(default="", description="Additional context")
    persona: str = Field(default="", description="Commenter persona")


class DraftReplyRequest(BaseModel):
    comment_text: str = Field(min_length=1, description="The comment to reply to")
    original_post: str = Field(default="", description="Original post context")
    context: str = Field(default="", description="Additional context")


class HumanizeRequest(BaseModel):
    text: str = Field(min_length=1, description="AI-generated text to humanize")
    style: str = Field(default="conversational", description="Target style")


class ExtractHooksRequest(BaseModel):
    content: str = Field(min_length=1, description="LinkedIn content to analyze")
    additional_examples: list[str] = Field(default_factory=list)


class PlanContentRequest(BaseModel):
    business_goals: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    audience: str = Field(default="")
    week_start: str = Field(default="")


class RepurposeRequest(BaseModel):
    source_content: str = Field(min_length=1)
    transformation_type: str = Field(
        min_length=1,
        description="blog_to_post, video_to_post, thread_to_single, report_to_post",
    )
    target_audience: str = Field(default="")


class AuditPostRequest(BaseModel):
    post_text: str = Field(min_length=1)
    goal: str = Field(default="")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/skills/draft-post")
def api_draft_post(request: DraftPostRequest) -> dict[str, Any]:
    """Generate a LinkedIn post draft."""
    return generate_post_draft(
        topic=request.topic,
        audience=request.audience,
        goal=request.goal,
        tone=request.tone,
    )


@router.post("/skills/draft-comment")
def api_draft_comment(request: DraftCommentRequest) -> dict[str, Any]:
    """Draft a comment on a LinkedIn post."""
    return draft_comment(
        post_text=request.post_text,
        context=request.context,
        persona=request.persona,
    )


@router.post("/skills/draft-reply")
def api_draft_reply(request: DraftReplyRequest) -> dict[str, Any]:
    """Draft a reply to a LinkedIn comment."""
    return draft_reply(
        comment_text=request.comment_text,
        original_post=request.original_post,
        context=request.context,
    )


@router.post("/skills/humanize")
def api_humanize(request: HumanizeRequest) -> dict[str, Any]:
    """Rewrite AI-generated content to sound more human."""
    return humanize_text(
        text=request.text,
        style=request.style,
    )


@router.post("/skills/extract-hooks")
def api_extract_hooks(request: ExtractHooksRequest) -> dict[str, Any]:
    """Extract and analyze hooks from LinkedIn content."""
    return extract_hooks(
        content=request.content,
        additional_examples=request.additional_examples,
    )


@router.post("/skills/plan-content")
def api_plan_content(request: PlanContentRequest) -> dict[str, Any]:
    """Create a LinkedIn content calendar."""
    return plan_content(
        business_goals=request.business_goals,
        topics=request.topics,
        audience=request.audience,
        week_start=request.week_start,
    )


@router.post("/skills/repurpose")
def api_repurpose(request: RepurposeRequest) -> dict[str, Any]:
    """Transform content into LinkedIn-optimized format."""
    return repurpose_content(
        source_content=request.source_content,
        transformation_type=request.transformation_type,
        target_audience=request.target_audience,
    )


@router.post("/skills/audit")
def api_audit_post(request: AuditPostRequest) -> dict[str, Any]:
    """Analyze a LinkedIn post for quality."""
    return audit_post(
        post_text=request.post_text,
        goal=request.goal,
    )


# ---------------------------------------------------------------------------
# Health / config
# ---------------------------------------------------------------------------

@router.get("/skills/config")
def get_linkedin_skills_config() -> dict[str, Any]:
    """Get LinkedIn Skills configuration (no secrets)."""
    return {
        "capabilities": 8,
        "credentials_required": False,
        "skills": [
            "draft_post",
            "draft_comment",
            "draft_reply",
            "humanize",
            "extract_hooks",
            "plan_content",
            "repurpose",
            "audit_post",
        ],
        "note": "All 8 capabilities work without LinkedIn credentials. Drafting and analysis only.",
    }
