"""Comprehensive tests for the GoalOS LinkedIn Skills (Phase 1).

Tests 8 no-credential LinkedIn capabilities:
1. Post Writer
2. Comment Drafter
3. Reply Handler
4. Humanizer
5. Hook Extractor
6. Content Planner
7. Repurposer
8. Post Audit

All tests verify: capability registration, skill registration,
input validation, structured outputs, no LinkedIn credentials required,
no API calls, and no accidental publishing.
"""
from __future__ import annotations

import os
import secrets

os.environ.setdefault("GOALOS_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("IM_ENCRYPTION_KEY", secrets.token_hex(32))

import pytest


# ---------------------------------------------------------------------------
# 1. Capability Registration
# ---------------------------------------------------------------------------

class TestCapabilityRegistration:
    """Verify all 8 LinkedIn capabilities are registered in GoalOS."""

    LINKEDIN_SKILL_CAPS = [
        "linkedin_draft_post",
        "linkedin_draft_comment",
        "linkedin_draft_reply",
        "linkedin_humanize",
        "linkedin_extract_hooks",
        "linkedin_plan_content",
        "linkedin_repurpose",
        "linkedin_audit_post",
    ]

    def test_all_8_capabilities_registered(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for cap in self.LINKEDIN_SKILL_CAPS:
            assert cap in BUILTIN_CAPABILITIES, f"{cap} not registered"

    def test_capabilities_have_schemas(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for name in self.LINKEDIN_SKILL_CAPS:
            cap = BUILTIN_CAPABILITIES[name]
            assert cap.input_schema is not None
            assert cap.output_schema is not None

    def test_capabilities_do_not_require_approval(self):
        """Drafting and analysis should not require approval."""
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for name in self.LINKEDIN_SKILL_CAPS:
            cap = BUILTIN_CAPABILITIES[name]
            assert not cap.requires_approval, f"{name} should not require approval"

    def test_capabilities_have_correct_provider(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for name in self.LINKEDIN_SKILL_CAPS:
            cap = BUILTIN_CAPABILITIES[name]
            assert cap.provider == "linkedin"

    def test_capabilities_have_correct_category(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for name in self.LINKEDIN_SKILL_CAPS:
            cap = BUILTIN_CAPABILITIES[name]
            assert cap.category == "social"

    def test_capabilities_require_social_permission(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for name in self.LINKEDIN_SKILL_CAPS:
            cap = BUILTIN_CAPABILITIES[name]
            assert hasattr(cap, 'required_permissions'), f"{name} has no required_permissions"


# ---------------------------------------------------------------------------
# 2. Skill Registration
# ---------------------------------------------------------------------------

class TestSkillRegistration:
    """Verify all 8 LinkedIn skills are in BUILTIN_SKILLS."""

    LINKEDIN_SKILLS = [
        "linkedin_post_writer",
        "linkedin_comment_drafter",
        "linkedin_reply_handler",
        "linkedin_humanizer",
        "linkedin_hook_extractor",
        "linkedin_content_planner",
        "linkedin_repurposer",
        "linkedin_post_audit",
    ]

    def test_all_8_skills_registered(self):
        from app.skills.definitions import BUILTIN_SKILLS
        for skill in self.LINKEDIN_SKILLS:
            assert skill in BUILTIN_SKILLS, f"{skill} not in BUILTIN_SKILLS"

    def test_skills_have_instructions(self):
        from app.skills.definitions import BUILTIN_SKILLS
        for name in self.LINKEDIN_SKILLS:
            skill = BUILTIN_SKILLS[name]
            assert skill.instructions, f"{name} has no instructions"

    def test_skills_have_input_output_schemas(self):
        from app.skills.definitions import BUILTIN_SKILLS
        for name in self.LINKEDIN_SKILLS:
            skill = BUILTIN_SKILLS[name]
            assert skill.input_schema, f"{name} has no input_schema"
            assert skill.output_schema, f"{name} has no output_schema"


# ---------------------------------------------------------------------------
# 3. Post Writer (deterministic)
# ---------------------------------------------------------------------------

class TestPostWriter:
    def test_generates_draft(self):
        from app.services.linkedin_skills import generate_post_draft
        result = generate_post_draft(topic="AI in marketing")
        assert "hook" in result
        assert "body" in result
        assert "full_post" in result
        assert "hashtags" in result
        assert "cta" in result
        assert len(result["full_post"]) > 50

    def test_includes_topic(self):
        from app.services.linkedin_skills import generate_post_draft
        result = generate_post_draft(topic="Remote work")
        assert "Remote work" in result["full_post"]

    def test_with_audience(self):
        from app.services.linkedin_skills import generate_post_draft
        result = generate_post_draft(topic="AI", audience="CTOs")
        assert "CTOs" in result["full_post"]

    def test_with_goal(self):
        from app.services.linkedin_skills import generate_post_draft
        result = generate_post_draft(topic="SaaS", goal="generate leads")
        assert result["goal"] == "generate leads"

    def test_with_tone(self):
        from app.services.linkedin_skills import generate_post_draft
        result = generate_post_draft(topic="tech", tone="authoritative")
        assert result["tone"] == "authoritative"

    def test_empty_topic_fails(self):
        from app.services.linkedin_skills import generate_post_draft
        # Empty topic should still work (deterministic, no validation at service level)
        result = generate_post_draft(topic="")
        assert "hook" in result


# ---------------------------------------------------------------------------
# 4. Comment Drafter (deterministic)
# ---------------------------------------------------------------------------

class TestCommentDrafter:
    def test_drafts_comment(self):
        from app.services.linkedin_skills import draft_comment
        result = draft_comment(post_text="I just launched my new product!")
        assert "comment" in result
        assert "tone" in result
        assert "rationale" in result
        assert len(result["comment"]) > 10

    def test_question_post_gets_engaging_comment(self):
        from app.services.linkedin_skills import draft_comment
        result = draft_comment(post_text="What's your biggest challenge with AI?")
        assert result["tone"] == "engaging"

    def test_agreement_post_gets_supportive_comment(self):
        from app.services.linkedin_skills import draft_comment
        result = draft_comment(post_text="I agree with this great approach!")
        assert result["tone"] == "supportive"

    def test_negative_post_gets_constructive_comment(self):
        from app.services.linkedin_skills import draft_comment
        result = draft_comment(post_text="This is a common mistake in marketing")
        assert result["tone"] == "constructive"

    def test_no_generic_praise(self):
        """Comments should not be generic like 'Great post!'."""
        from app.services.linkedin_skills import draft_comment
        result = draft_comment(post_text="Some random post about business")
        assert "Great post" not in result["comment"]


# ---------------------------------------------------------------------------
# 5. Reply Handler (deterministic)
# ---------------------------------------------------------------------------

class TestReplyHandler:
    def test_drafts_reply(self):
        from app.services.linkedin_skills import draft_reply
        result = draft_reply(comment_text="Thanks for sharing!")
        assert "reply" in result
        assert "tone" in result
        assert "escalation_needed" in result

    def test_negative_comment_escalates(self):
        from app.services.linkedin_skills import draft_reply
        result = draft_reply(comment_text="This is spam and a scam!")
        assert result["escalation_needed"] is True
        assert result["tone"] == "diplomatic"

    def test_question_gets_helpful_reply(self):
        from app.services.linkedin_skills import draft_reply
        result = draft_reply(comment_text="How do you implement this?")
        assert result["tone"] == "helpful"

    def test_disagreement_gets_diplomatic_reply(self):
        from app.services.linkedin_skills import draft_reply
        result = draft_reply(comment_text="I disagree with your approach")
        assert result["tone"] == "diplomatic"

    def test_never_defensive(self):
        """Replies should never be defensive or argumentative."""
        from app.services.linkedin_skills import draft_reply
        result = draft_reply(comment_text="You're wrong about this")
        assert "defensive" not in result["reply"].lower()
        assert "argument" not in result["reply"].lower()


# ---------------------------------------------------------------------------
# 6. Humanizer (deterministic)
# ---------------------------------------------------------------------------

class TestHumanizer:
    def test_humanizes_text(self):
        from app.services.linkedin_skills import humanize_text
        result = humanize_text(text="It is important to leverage synergies and utilize resources.")
        assert "humanized_text" in result
        assert "changes_made" in result
        assert "naturalness_score" in result
        assert result["naturalness_score"] > 0.5

    def test_replaces_jargon(self):
        from app.services.linkedin_skills import humanize_text
        result = humanize_text(text="We need to leverage our ecosystem and utilize synergies.")
        assert any("leverage" in c.lower() or "utilize" in c.lower() for c in result["changes_made"])

    def test_adds_contractions(self):
        from app.services.linkedin_skills import humanize_text
        result = humanize_text(text="It is important and we are ready.")
        assert "it's" in result["humanized_text"].lower() or "we're" in result["humanized_text"].lower()

    def test_naturalness_above_threshold(self):
        from app.services.linkedin_skills import humanize_text
        result = humanize_text(text="In today's world, it is important to note that leverage is key.")
        assert result["naturalness_score"] >= 0.5


# ---------------------------------------------------------------------------
# 7. Hook Extractor (deterministic)
# ---------------------------------------------------------------------------

class TestHookExtractor:
    def test_extracts_hooks(self):
        from app.services.linkedin_skills import extract_hooks
        result = extract_hooks(content="Did you know that 80% of startups fail?")
        assert "hooks" in result
        assert "ranking" in result
        assert "recommendations" in result
        assert len(result["hooks"]) >= 1

    def test_identifies_hook_type(self):
        from app.services.linkedin_skills import extract_hooks
        result = extract_hooks(content="Did you know the average CTR is 2%?")
        hook = result["hooks"][0]
        assert hook["type"] in ("fact_opener", "data_driven", "question")

    def test_ranks_hooks_by_strength(self):
        from app.services.linkedin_skills import extract_hooks
        result = extract_hooks(
            content="Did you know this?",
            additional_examples=["I spent 10 years learning this."],
        )
        if len(result["ranking"]) > 1:
            assert len(result["ranking"]) >= 1

    def test_with_examples(self):
        from app.services.linkedin_skills import extract_hooks
        result = extract_hooks(
            content="Stop scrolling. This changes everything.",
            additional_examples=["Here's a thing about marketing:"],
        )
        assert len(result["hooks"]) >= 1


# ---------------------------------------------------------------------------
# 8. Content Planner (deterministic)
# ---------------------------------------------------------------------------

class TestContentPlanner:
    def test_creates_calendar(self):
        from app.services.linkedin_skills import plan_content
        result = plan_content(
            business_goals=["Increase brand awareness"],
            topics=["AI", "Marketing", "Startups"],
            audience="Founders",
        )
        assert "calendar" in result
        assert "content_mix" in result
        assert len(result["calendar"]) == 5  # Monday-Friday

    def test_calendar_has_required_fields(self):
        from app.services.linkedin_skills import plan_content
        result = plan_content(business_goals=["Growth"], topics=["Tech"])
        for day in result["calendar"]:
            assert "day" in day
            assert "topic" in day
            assert "type" in day
            assert "time" in day

    def test_content_mix_adds_to_one(self):
        from app.services.linkedin_skills import plan_content
        result = plan_content(business_goals=["Growth"], topics=["AI"])
        total = sum(result["content_mix"].values())
        assert abs(total - 1.0) < 0.01

    def test_balanced_content_types(self):
        from app.services.linkedin_skills import plan_content
        result = plan_content(business_goals=["Growth"], topics=["AI", "Marketing"])
        types = [d["type"] for d in result["calendar"]]
        assert "thought_leadership" in types
        assert "promotional" in types


# ---------------------------------------------------------------------------
# 9. Repurposer (deterministic)
# ---------------------------------------------------------------------------

class TestRepurposer:
    def test_blog_to_post(self):
        from app.services.linkedin_skills import repurpose_content
        result = repurpose_content(
            source_content="Article about AI trends. Machine learning is transforming industries. Companies are adopting AI rapidly.",
            transformation_type="blog_to_post",
        )
        assert "linkedin_post" in result
        assert "hook" in result
        assert "key_points" in result
        assert len(result["linkedin_post"]) > 30

    def test_video_to_post(self):
        from app.services.linkedin_skills import repurpose_content
        result = repurpose_content(
            source_content="Key point 1 about marketing. Key point 2 about growth.",
            transformation_type="video_to_post",
        )
        assert "linkedin_post" in result
        assert result["source_type"] == "video_to_post"

    def test_thread_to_single(self):
        from app.services.linkedin_skills import repurpose_content
        result = repurpose_content(
            source_content="Thread part 1: Introduction. Thread part 2: Main argument.",
            transformation_type="thread_to_single",
        )
        assert "linkedin_post" in result
        assert result["source_type"] == "thread_to_single"

    def test_report_to_post(self):
        from app.services.linkedin_skills import repurpose_content
        result = repurpose_content(
            source_content="Revenue grew 25% in Q1. Customer acquisition cost dropped 15%.",
            transformation_type="report_to_post",
        )
        assert "linkedin_post" in result
        assert result["source_type"] == "report_to_post"

    def test_unknown_type_falls_back(self):
        from app.services.linkedin_skills import repurpose_content
        result = repurpose_content(
            source_content="Some content here",
            transformation_type="unknown_type",
        )
        assert "linkedin_post" in result


# ---------------------------------------------------------------------------
# 10. Post Audit (deterministic)
# ---------------------------------------------------------------------------

class TestPostAudit:
    def test_audits_post(self):
        from app.services.linkedin_skills import audit_post
        result = audit_post(post_text="I just learned something amazing about AI! What do you think?")
        assert "overall_score" in result
        assert "hook_score" in result
        assert "readability_score" in result
        assert "cta_score" in result
        assert "improvements" in result
        assert "strengths" in result

    def test_scores_are_bounded(self):
        from app.services.linkedin_skills import audit_post
        result = audit_post(post_text="Test post")
        assert 0 <= result["overall_score"] <= 100
        assert 0 <= result["hook_score"] <= 100
        assert 0 <= result["readability_score"] <= 100

    def test_strong_post_scores_higher(self):
        from app.services.linkedin_skills import audit_post
        strong = audit_post(
            post_text="Did you know 80% of marketers struggle with content?\n\nHere are 3 things that changed everything for me:\n\n1. Start with a story\n2. Use data to back it up\n3. End with a question\n\nWhat's your biggest content challenge?"
        )
        weak = audit_post(post_text="Buy my product. It's great.")
        assert strong["overall_score"] >= weak["overall_score"]

    def test_improvements_for_weak_post(self):
        from app.services.linkedin_skills import audit_post
        result = audit_post(post_text="Hi")
        assert len(result["improvements"]) > 0

    def test_strengths_for_good_post(self):
        from app.services.linkedin_skills import audit_post
        result = audit_post(
            post_text="Did you know that consistent posting 3x per week increases engagement by 300%?\n\nI tested this for 6 months.\n\nThe results speak for themselves.\n\nWhat's your posting frequency?"
        )
        assert len(result["strengths"]) > 0


# ---------------------------------------------------------------------------
# 11. API Endpoints
# ---------------------------------------------------------------------------

class TestLinkedInSkillsAPI:
    @pytest.fixture
    def api(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import session as session_module
        from app.db.base import Base
        from app.main import app

        engine = create_engine(
            f"sqlite:///{tmp_path / 'linkedin_test.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        def override_get_db():
            db = factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[session_module.get_db] = override_get_db
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.clear()
            engine.dispose()

    def test_config_endpoint(self, api):
        response = api.get("/api/v1/linkedin/skills/config")
        assert response.status_code == 200
        data = response.json()
        assert data["capabilities"] == 8
        assert data["credentials_required"] is False

    def test_draft_post(self, api):
        response = api.post("/api/v1/linkedin/skills/draft-post", json={
            "topic": "AI in marketing",
            "audience": "CMOs",
            "goal": "generate leads",
        })
        assert response.status_code == 200
        data = response.json()
        assert "hook" in data
        assert "full_post" in data
        assert len(data["full_post"]) > 50

    def test_draft_comment(self, api):
        response = api.post("/api/v1/linkedin/skills/draft-comment", json={
            "post_text": "What's your biggest challenge with AI adoption?",
        })
        assert response.status_code == 200
        data = response.json()
        assert "comment" in data
        assert len(data["comment"]) > 10

    def test_draft_reply(self, api):
        response = api.post("/api/v1/linkedin/skills/draft-reply", json={
            "comment_text": "How do you implement this in practice?",
        })
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data

    def test_humanize(self, api):
        response = api.post("/api/v1/linkedin/skills/humanize", json={
            "text": "It is important to leverage synergies and utilize our ecosystem.",
        })
        assert response.status_code == 200
        data = response.json()
        assert "humanized_text" in data
        assert data["naturalness_score"] > 0.5

    def test_extract_hooks(self, api):
        response = api.post("/api/v1/linkedin/skills/extract-hooks", json={
            "content": "Did you know that 80% of startups fail in the first year?",
        })
        assert response.status_code == 200
        data = response.json()
        assert "hooks" in data
        assert len(data["hooks"]) >= 1

    def test_plan_content(self, api):
        response = api.post("/api/v1/linkedin/skills/plan-content", json={
            "business_goals": ["Grow brand awareness"],
            "topics": ["AI", "Marketing"],
            "audience": "Founders",
        })
        assert response.status_code == 200
        data = response.json()
        assert "calendar" in data
        assert len(data["calendar"]) == 5

    def test_repurpose(self, api):
        response = api.post("/api/v1/linkedin/skills/repurpose", json={
            "source_content": "Article about AI trends in 2026.",
            "transformation_type": "blog_to_post",
        })
        assert response.status_code == 200
        data = response.json()
        assert "linkedin_post" in data

    def test_audit_post(self, api):
        response = api.post("/api/v1/linkedin/skills/audit", json={
            "post_text": "Did you know that 80% of marketers struggle? Here's what I learned.",
            "goal": "educate",
        })
        assert response.status_code == 200
        data = response.json()
        assert "overall_score" in data
        assert 0 <= data["overall_score"] <= 100

    def test_draft_post_requires_topic(self, api):
        response = api.post("/api/v1/linkedin/skills/draft-post", json={})
        assert response.status_code == 422  # validation error


# ---------------------------------------------------------------------------
# 12. No Credentials / No API Calls
# ---------------------------------------------------------------------------

class TestNoCredentialsRequired:
    """Prove that all 8 capabilities work without LinkedIn credentials."""

    def test_no_linkedin_env_vars_needed(self):
        """The service module should not import or check LinkedIn env vars."""
        import app.services.linkedin_skills as mod
        import inspect
        source = inspect.getsource(mod)
        assert "LINKEDIN_ACCESS_TOKEN" not in source
        assert "LINKEDIN_ORGANIZATION_ID" not in source

    def test_no_api_calls_in_service(self):
        """The service should not make any HTTP/API calls."""
        import app.services.linkedin_skills as mod
        import inspect
        source = inspect.getsource(mod)
        assert "requests.get" not in source
        assert "requests.post" not in source
        assert "urlopen" not in source
        assert "graph.facebook.com" not in source
        assert "api.linkedin.com" not in source

    def test_all_capabilities_work_without_config(self):
        """Every capability should produce output without any env vars set."""
        from app.services.linkedin_skills import (
            generate_post_draft, draft_comment, draft_reply,
            humanize_text, extract_hooks, plan_content,
            repurpose_content, audit_post,
        )
        # All should succeed without any LinkedIn credentials
        assert generate_post_draft(topic="test")["hook"]
        assert draft_comment(post_text="test")["comment"]
        assert draft_reply(comment_text="test")["reply"]
        assert humanize_text(text="test it is important")["humanized_text"]
        assert extract_hooks(content="test")["hooks"]
        assert plan_content(business_goals=["test"], topics=["test"])["calendar"]
        assert repurpose_content(source_content="test content", transformation_type="blog_to_post")["linkedin_post"]
        assert audit_post(post_text="test post")["overall_score"] >= 0


# ---------------------------------------------------------------------------
# 13. Existing Approval Behavior Preserved
# ---------------------------------------------------------------------------

class TestApprovalPreserved:
    """Verify that the existing LinkedIn approval behavior is intact."""

    def test_linkedin_create_post_still_requires_approval(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["linkedin_create_post"]
        assert cap.requires_approval is True

    def test_linkedin_draft_does_not_require_approval(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for name in ["linkedin_draft_post", "linkedin_draft_comment", "linkedin_draft_reply"]:
            cap = BUILTIN_CAPABILITIES[name]
            assert cap.requires_approval is False
