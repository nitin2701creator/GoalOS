"""Idea generation for the Viral Idea Finder.

Takes a cluster of related content items and produces:
- A unified title and summary
- The underlying topic
- Why it matters
- Multiple actionable content angles

All output is deterministic and derived from the collected evidence.
No LLM calls — this is template-based for the MVP.
"""

from __future__ import annotations

from typing import Any


def _extract_key_phrases(texts: list[str], top_n: int = 5) -> list[str]:
    """Extract the most frequent meaningful words/phrases from texts."""
    from collections import Counter
    import re

    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "and", "but", "or", "not", "so", "this", "that", "these", "those",
        "it", "its", "new", "also", "about", "just", "more", "how", "what",
        "which", "when", "where", "who", "why", "all", "their", "they",
        "has", "been", "one", "two", "first", "last", "get", "make", "like",
        "over", "most", "than", "some", "very", "only", "even", "back",
        "after", "use", "way", "many", "well", "much", "say", "know",
    }

    word_counts: Counter[str] = Counter()
    for text in texts:
        words = re.sub(r"[^\w\s]", " ", text.lower()).split()
        for word in words:
            if len(word) > 3 and word not in stop_words:
                word_counts[word] += 1

    return [word for word, _ in word_counts.most_common(top_n)]


def generate_title(items: list[dict[str, Any]]) -> str:
    """Generate a descriptive title for a cluster of items."""
    key_phrases = _extract_key_phrases(
        [it.get("title", "") for it in items], top_n=3
    )
    if key_phrases:
        topic = " / ".join(key_phrases[:2])
        return f"Trending: {topic.title()}"
    # Fallback: use the most frequent word from the first item title
    first_title = items[0].get("title", "Unknown Trend") if items else "Unknown Trend"
    return f"Trending: {first_title[:80]}"


def generate_summary(items: list[dict[str, Any]], topic: str) -> str:
    """Generate a summary describing the trend across the cluster."""
    source_count = len(items)
    platforms = sorted({it.get("source", "unknown") for it in items})
    platform_str = ", ".join(platforms[:3])

    titles = [it.get("title", "") for it in items if it.get("title")]
    if titles:
        top_titles = titles[:3]
        title_str = "; ".join(top_titles)
        return (
            f"{source_count} content items from {platform_str} discuss "
            f"topics related to: {title_str}"
        )
    return f"{source_count} content items from {platform_str} discuss {topic}"


def generate_why_it_matters(
    items: list[dict[str, Any]],
    scores: dict[str, Any],
) -> str:
    """Generate an explanation of why this trend matters."""
    parts: list[str] = []

    viral_score = scores.get("viral_score", 0)
    cross_score = scores.get("cross_source_score", 0)
    momentum = scores.get("momentum_score", 0)

    if cross_score >= 0.5:
        platforms = sorted({it.get("source", "unknown") for it in items})
        parts.append(
            f"This topic is appearing across multiple platforms ({', '.join(platforms[:4])}), "
            "indicating broad interest."
        )

    if momentum >= 0.5:
        parts.append("Engagement signals show strong momentum.")

    if viral_score >= 0.7:
        parts.append("High viral score suggests significant potential for content creation.")
    elif viral_score >= 0.4:
        parts.append("Moderate viral potential — worth monitoring for content opportunities.")
    else:
        parts.append("Early-stage signal — could grow if momentum continues.")

    if len(items) >= 5:
        parts.append(
            f"High volume ({len(items)} items) indicates this is an active conversation."
        )

    return " ".join(parts) if parts else "This trend shows emerging interest."


# Content angle templates
ANGLE_TEMPLATES: list[dict[str, str]] = [
    {
        "type": "educational",
        "template": "Create an in-depth educational piece explaining the key concepts behind {topic}, "
        "targeting audiences who are encountering this for the first time.",
    },
    {
        "type": "contrarian",
        "template": "Write a contrarian take challenging the mainstream narrative around {topic}, "
        "presenting a well-reasoned alternative perspective.",
    },
    {
        "type": "short_form_video",
        "template": "Produce a short-form video (60-90s) breaking down {topic} "
        "with visual explanations and key takeaways.",
    },
    {
        "type": "business_opportunity",
        "template": "Analyze the business opportunities emerging from {topic} — "
        "who benefits, what market gaps exist, and where to position.",
    },
    {
        "type": "experiment",
        "template": "Design a content experiment around {topic}: test 3 different angles "
        "across platforms to see which resonates most with the audience.",
    },
]


def generate_content_angles(items: list[dict[str, Any]], topic: str) -> list[str]:
    """Generate actionable content angles for the trend."""
    angles: list[str] = []
    for template_info in ANGLE_TEMPLATES:
        angle = template_info["template"].format(topic=topic)
        angles.append(angle)
    return angles


def generate_topic(items: list[dict[str, Any]]) -> str:
    """Determine the topic from a cluster of items."""
    key_phrases = _extract_key_phrases(
        [it.get("title", "") for it in items], top_n=3
    )
    if key_phrases:
        return " / ".join(key_phrases[:2]).title()
    # Fallback to source topic if available
    for it in items:
        if it.get("topic"):
            return it["topic"]
    return "General Trend"
