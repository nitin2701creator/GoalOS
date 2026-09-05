"""LinkedIn intelligence layer for GoalOS.

Implements 8 no-credential LinkedIn capabilities:
1. Post Writer — generate LinkedIn post drafts
2. Comment Drafter — draft comments on posts
3. Reply Handler — draft replies to comments
4. Humanizer — rewrite AI content to sound natural
5. Hook Extractor — analyze and extract hook patterns
6. Content Planner — create content calendars
7. Repurposer — transform content for LinkedIn
8. Post Audit — analyze post quality

These are research/drafting/analysis tools — they do not publish to LinkedIn.
No LinkedIn credentials required for any capability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Hook pattern analysis (deterministic, no LLM needed)
# ---------------------------------------------------------------------------

_HOOK_PATTERNS: list[dict[str, Any]] = [
    {"pattern": r"^(Did you know|Fun fact|Here'?s a thing)", "type": "fact_opener", "trigger": "curiosity"},
    {"pattern": r"^\d+[\.\)]\s", "type": "list_opener", "trigger": "structure"},
    {"pattern": r"^(I |My |We )", "type": "personal_story", "trigger": "authenticity"},
    {"pattern": r"(Stop |Don'?t |Never |Always )", "type": "imperative", "trigger": "authority"},
    {"pattern": r"\?", "type": "question", "trigger": "engagement"},
    {"pattern": r"(\d+%|\d+x|\$\d+)", "type": "data_driven", "trigger": "credibility"},
    {"pattern": r"^(Unpopular opinion|Hot take|Controversial)", "type": "contrarian", "trigger": "debate"},
    {"pattern": r"^(When I |After |Before )", "type": "narrative", "trigger": "storytelling"},
]


def _extract_hooks_from_text(text: str) -> list[dict[str, Any]]:
    """Extract hooks from text using pattern analysis."""
    hooks = []
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    first_line = lines[0] if lines else ""

    for pat in _HOOK_PATTERNS:
        if re.search(pat["pattern"], first_line, re.IGNORECASE):
            hooks.append({
                "text": first_line,
                "type": pat["type"],
                "trigger": pat["trigger"],
                "strength": 0.7,
            })
            break

    if not hooks and first_line:
        hooks.append({
            "text": first_line,
            "type": "generic",
            "trigger": "attention",
            "strength": 0.4,
        })

    return hooks


# ---------------------------------------------------------------------------
# Content quality scoring (deterministic)
# ---------------------------------------------------------------------------

def _score_post_quality(text: str, goal: str = "") -> dict[str, Any]:
    """Score a LinkedIn post across multiple dimensions."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    total_chars = len(text)
    total_lines = len(lines)

    # Hook score (first line)
    hook_score = 0.3
    first_line = lines[0] if lines else ""
    if len(first_line) > 10 and len(first_line) < 200:
        hook_score = 0.6
    if re.search(r"\?|!|\d+%|\d+x", first_line):
        hook_score = 0.8
    if any(re.search(p["pattern"], first_line, re.IGNORECASE) for p in _HOOK_PATTERNS if p["trigger"] in ("curiosity", "engagement", "authority")):
        hook_score = min(hook_score + 0.15, 1.0)

    # Readability score (short paragraphs, line breaks)
    avg_line_length = total_chars / max(total_lines, 1)
    readability = 0.5
    if avg_line_length < 120:
        readability = 0.8
    elif avg_line_length < 200:
        readability = 0.6
    if total_lines >= 5:
        readability = min(readability + 0.1, 1.0)

    # CTA score
    cta_score = 0.2
    cta_patterns = r"(comment|share|follow|subscribe|try|start|learn|visit|click|tag|what do you think|your thoughts|agree)"
    if re.search(cta_patterns, text, re.IGNORECASE):
        cta_score = 0.7
    if text.rstrip().endswith("?"):
        cta_score = min(cta_score + 0.15, 1.0)

    # Emotional pull
    emotional = 0.4
    emotional_words = r"(amazing|incredible|secret|discover|transform|breakthrough|struggle|fail|success|love|hate|fear|dream)"
    matches = len(re.findall(emotional_words, text, re.IGNORECASE))
    emotional = min(0.4 + matches * 0.08, 1.0)

    # Authenticity (penalize corporate jargon)
    authenticity = 0.8
    jargon = r"(leverage|synergy|optimize|utilize|facilitate|streamline|paradigm|ecosystem|holistic|deep dive)"
    jargon_matches = len(re.findall(jargon, text, re.IGNORECASE))
    authenticity = max(0.8 - jargon_matches * 0.15, 0.1)

    # Overall
    overall = (hook_score * 0.25 + readability * 0.2 + cta_score * 0.2 +
               emotional * 0.15 + authenticity * 0.2)

    return {
        "overall_score": round(overall * 100),
        "hook_score": round(hook_score * 100),
        "readability_score": round(readability * 100),
        "cta_score": round(cta_score * 100),
        "emotional_score": round(emotional * 100),
        "authenticity_score": round(authenticity * 100),
    }


def _identify_improvements(text: str, scores: dict[str, Any]) -> list[str]:
    """Identify specific improvement suggestions."""
    improvements = []
    if scores["hook_score"] < 60:
        improvements.append("Strengthen the hook — try a question, statistic, or bold claim in the first line")
    if scores["readability_score"] < 60:
        improvements.append("Break up long paragraphs — use shorter lines and more line breaks")
    if scores["cta_score"] < 50:
        improvements.append("Add a clear call to action — ask a question or invite engagement")
    if scores["emotional_score"] < 50:
        improvements.append("Add emotional triggers — personal stories, surprising facts, or strong opinions")
    if scores["authenticity_score"] < 60:
        improvements.append("Remove corporate jargon — use conversational, natural language instead")
    if not text.rstrip().endswith("?") and scores["cta_score"] < 70:
        improvements.append("Consider ending with a question to drive comments")
    if len(text) > 1300:
        improvements.append("Post is long — LinkedIn optimal length is 1,200-1,500 characters")
    if len(text) < 200:
        improvements.append("Post is very short — add more substance or a story")
    return improvements


def _identify_strengths(text: str, scores: dict[str, Any]) -> list[str]:
    """Identify what the post does well."""
    strengths = []
    if scores["hook_score"] >= 70:
        strengths.append("Strong opening hook that stops the scroll")
    if scores["readability_score"] >= 70:
        strengths.append("Good readability with short paragraphs and line breaks")
    if scores["cta_score"] >= 60:
        strengths.append("Clear call to action that encourages engagement")
    if scores["emotional_score"] >= 60:
        strengths.append("Effective emotional triggers that resonate")
    if scores["authenticity_score"] >= 70:
        strengths.append("Authentic, human-sounding voice")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if 8 <= len(lines) <= 20:
        strengths.append("Good post length for LinkedIn engagement")
    return strengths


# ---------------------------------------------------------------------------
# Content calendar (deterministic templates)
# ---------------------------------------------------------------------------

_CONTENT_TYPES = [
    ("thought_leadership", 0.40),
    ("educational", 0.25),
    ("personal_story", 0.20),
    ("promotional", 0.15),
]

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

_DEFAULT_TIMES = {
    "thought_leadership": "8:00 AM",
    "educational": "10:00 AM",
    "personal_story": "12:00 PM",
    "promotional": "2:00 PM",
}


def _build_content_calendar(
    business_goals: list[str],
    topics: list[str],
    audience: str,
    week_start: str = "",
) -> dict[str, Any]:
    """Build a structured content calendar deterministically."""
    calendar = []
    topic_idx = 0
    goal_idx = 0

    for day in _DAYS:
        # Pick content type based on day distribution
        day_position = _DAYS.index(day)
        if day_position == 0:
            ctype = "thought_leadership"
        elif day_position == 1:
            ctype = "educational"
        elif day_position == 2:
            ctype = "personal_story"
        elif day_position == 3:
            ctype = "thought_leadership"
        else:
            ctype = "promotional"

        topic = topics[topic_idx % len(topics)] if topics else "General"
        goal = business_goals[goal_idx % len(business_goals)] if business_goals else "Engagement"
        topic_idx += 1
        goal_idx += 1

        hook_preview = f"分享一个关于 {topic} 的洞察" if ctype == "thought_leadership" else f"{topic}: What you need to know"

        calendar.append({
            "day": day,
            "topic": topic,
            "type": ctype,
            "hook": hook_preview,
            "time": _DEFAULT_TIMES.get(ctype, "9:00 AM"),
            "goal": goal,
        })

    total = len(calendar) or 1
    content_mix = {
        "thought_leadership": sum(1 for c in calendar if c["type"] == "thought_leadership") / total,
        "educational": sum(1 for c in calendar if c["type"] == "educational") / total,
        "personal": sum(1 for c in calendar if c["type"] == "personal_story") / total,
        "promotional": sum(1 for c in calendar if c["type"] == "promotional") / total,
    }

    return {"calendar": calendar, "content_mix": content_mix}


# ---------------------------------------------------------------------------
# Public API — called by the API endpoints
# ---------------------------------------------------------------------------

def generate_post_draft(
    topic: str,
    audience: str = "",
    goal: str = "",
    tone: str = "",
) -> dict[str, Any]:
    """Generate a LinkedIn post draft deterministically."""
    audience_text = f" for {audience}" if audience else ""
    goal_text = f" with the goal to {goal}" if goal else ""
    tone_text = f" in a {tone} tone" if tone else ""

    hook = f"Here's what most people get wrong about {topic}:"
    body_lines = [
        f"I've been thinking about {topic}{audience_text}{goal_text}{tone_text}.",
        "",
        "Here are the key insights:",
        "",
        "1. Start with why it matters to your audience",
        "2. Share a concrete example or case study",
        "3. End with an actionable takeaway",
        "",
        f"The bottom line: {topic} is evolving fast.",
        "",
        "What's your experience with this? I'd love to hear your perspective.",
    ]
    body = "\n".join(body_lines)

    hashtags = ["#LinkedIn", "#Growth", f"#{topic.replace(' ', '')}"]

    full_post = f"{hook}\n\n{body}\n\n{' '.join(hashtags)}"

    return {
        "hook": hook,
        "body": body,
        "hashtags": hashtags,
        "cta": "What's your experience with this?",
        "full_post": full_post,
        "audience": audience,
        "goal": goal,
        "tone": tone,
    }


def draft_comment(
    post_text: str,
    context: str = "",
    persona: str = "",
) -> dict[str, Any]:
    """Draft a LinkedIn comment deterministically."""
    post_lower = post_text.lower()

    if "?" in post_text:
        comment = "Great question! I think the key here is to focus on practical application rather than theory."
        tone = "engaging"
    elif any(w in post_lower for w in ["agree", "great", "love"]):
        comment = "Absolutely agree. This resonates with my experience — would love to discuss further."
        tone = "supportive"
    elif any(w in post_lower for w in ["mistake", "wrong", "fail"]):
        comment = "This is an important point. I've seen this pattern too and it's worth addressing early."
        tone = "constructive"
    else:
        comment = "Interesting perspective. I'd add that context matters a lot here — what works in one situation may not apply universally."
        tone = "thoughtful"

    rationale = f"Comment is {tone} and adds value beyond generic agreement"

    return {
        "comment": comment,
        "tone": tone,
        "rationale": rationale,
    }


def draft_reply(
    comment_text: str,
    original_post: str = "",
    context: str = "",
) -> dict[str, Any]:
    """Draft a LinkedIn reply deterministically."""
    comment_lower = comment_text.lower()

    escalation_needed = False

    if any(w in comment_lower for w in ["spam", "scam", "fake", "terrible"]):
        reply = "Thank you for your feedback. I appreciate you taking the time to share your perspective."
        tone = "diplomatic"
        escalation_needed = True
    elif "?" in comment_text:
        reply = "Great question! Let me clarify — the key insight is that results come from consistent application, not just knowledge."
        tone = "helpful"
    elif any(w in comment_lower for w in ["disagree", "wrong", "but"]):
        reply = "That's a valid point. I think we're both right in different contexts. What matters is finding what works for your specific situation."
        tone = "diplomatic"
    else:
        reply = "Thank you for engaging! I appreciate your perspective on this."
        tone = "appreciative"

    return {
        "reply": reply,
        "tone": tone,
        "escalation_needed": escalation_needed,
    }


def humanize_text(
    text: str,
    style: str = "conversational",
) -> dict[str, Any]:
    """Rewrite AI-generated content to sound more natural."""
    changes = []
    result = text

    # Replace corporate jargon
    replacements = {
        "leverage": "use",
        "utilize": "use",
        "facilitate": "help",
        "streamline": "simplify",
        "paradigm": "approach",
        "ecosystem": "environment",
        "holistic": "complete",
        "deep dive": "look at",
        "synergy": "collaboration",
        "In today's world": "Right now",
        "It is important to note": "Worth mentioning",
        "Furthermore": "Also",
        "Moreover": "Plus",
        "Consequently": "So",
    }

    for old, new in replacements.items():
        if old.lower() in result.lower():
            result = re.sub(re.escape(old), new, result, flags=re.IGNORECASE)
            changes.append(f"Replaced '{old}' with '{new}'")

    # Add contractions
    contractions = {
        "it is": "it's",
        "you are": "you're",
        "we are": "we're",
        "they are": "they're",
        "I am": "I'm",
        "do not": "don't",
        "does not": "doesn't",
        "will not": "won't",
        "cannot": "can't",
        "should not": "shouldn't",
    }
    for old, new in contractions.items():
        if old in result:
            result = result.replace(old, new)
            changes.append(f"Contracted '{old}' to '{new}'")

    # Calculate naturalness score
    naturalness = 0.5
    if changes:
        naturalness = min(0.5 + len(changes) * 0.05, 0.95)
    if "?" in result:
        naturalness = min(naturalness + 0.05, 0.95)
    if any(c in result for c in ["...", "—", "–"]):
        naturalness = min(naturalness + 0.05, 0.95)

    return {
        "humanized_text": result,
        "changes_made": changes,
        "naturalness_score": round(naturalness, 2),
    }


def extract_hooks(
    content: str,
    additional_examples: list[str] | None = None,
) -> dict[str, Any]:
    """Extract and analyze hooks from content."""
    all_content = [content] + (additional_examples or [])
    all_hooks = []

    for text in all_content:
        hooks = _extract_hooks_from_text(text)
        all_hooks.extend(hooks)

    # Rank by strength
    all_hooks.sort(key=lambda h: h.get("strength", 0), reverse=True)
    ranking = [h["text"] for h in all_hooks]

    recommendations = []
    if all_hooks:
        best = all_hooks[0]
        recommendations.append(f"Best hook type: {best['type']} (triggers {best['trigger']})")
        if best["strength"] < 0.6:
            recommendations.append("Consider using a question or statistic to boost engagement")
    recommendations.append("Test different hook types: questions, statistics, personal stories, bold claims")

    return {
        "hooks": all_hooks,
        "ranking": ranking,
        "recommendations": recommendations,
    }


def plan_content(
    business_goals: list[str],
    topics: list[str],
    audience: str = "",
    week_start: str = "",
) -> dict[str, Any]:
    """Create a LinkedIn content calendar."""
    return _build_content_calendar(business_goals, topics, audience, week_start)


def repurpose_content(
    source_content: str,
    transformation_type: str,
    target_audience: str = "",
) -> dict[str, Any]:
    """Transform content into LinkedIn-optimized format."""
    # Extract key sentences
    sentences = [s.strip() for s in re.split(r"[.!?\n]", source_content) if len(s.strip()) > 20]
    key_points = sentences[:5] if len(sentences) > 5 else sentences

    if transformation_type == "blog_to_post":
        hook = key_points[0] if key_points else "Here's what I learned from this article:"
        post_lines = [hook, ""]
        for point in key_points[:3]:
            post_lines.append(f"→ {point}")
        post_lines.append("")
        post_lines.append("What's your take on this?")
        linkedin_post = "\n".join(post_lines)

    elif transformation_type == "video_to_post":
        hook = f"Key takeaways from this video{'about ' + target_audience if target_audience else ''}:"
        post_lines = [hook, ""]
        for i, point in enumerate(key_points[:4], 1):
            post_lines.append(f"{i}. {point}")
        post_lines.append("")
        post_lines.append("Watch the full video for more context — link in comments.")
        linkedin_post = "\n".join(post_lines)

    elif transformation_type == "thread_to_single":
        hook = key_points[0] if key_points else "The most important insight:"
        linkedin_post = f"{hook}\n\n{' '.join(key_points[:3])}\n\nWhat resonates with you?"

    elif transformation_type == "report_to_post":
        hook = f"Here's what the data actually says:"
        post_lines = [hook, ""]
        for point in key_points[:3]:
            post_lines.append(f"📊 {point}")
        post_lines.append("")
        post_lines.append("Data doesn't lie — but context matters.")
        linkedin_post = "\n".join(post_lines)

    else:
        hook = "Here's the key insight:"
        linkedin_post = f"{hook}\n\n{source_content[:500]}\n\nThoughts?"

    return {
        "linkedin_post": linkedin_post,
        "hook": hook,
        "key_points": key_points,
        "source_type": transformation_type,
    }


def audit_post(
    post_text: str,
    goal: str = "",
) -> dict[str, Any]:
    """Analyze a LinkedIn post for quality."""
    scores = _score_post_quality(post_text, goal)
    improvements = _identify_improvements(post_text, scores)
    strengths = _identify_strengths(post_text, scores)

    return {
        **scores,
        "improvements": improvements,
        "strengths": strengths,
    }
