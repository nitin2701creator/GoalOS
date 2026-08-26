"""Deterministic viral scoring for the Viral Idea Finder.

Every score is derived from observable evidence and returns an
explanation string so results are fully auditable.  No ML models
are used — this is heuristic-based for the MVP.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

# Weights for the composite viral score
_WEIGHTS = {
    "engagement": 0.25,
    "recency": 0.20,
    "cross_source": 0.25,
    "novelty": 0.15,
    "momentum": 0.15,
}


def score_engagement(engagement: dict[str, Any]) -> tuple[float, str]:
    """Score based on available engagement metrics.

    Returns (score 0.0-1.0, explanation).
    """
    if not engagement:
        return 0.0, "No engagement metrics available"

    # Sum all numeric values as a raw engagement signal
    raw = 0.0
    for key, val in engagement.items():
        if isinstance(val, (int, float)):
            raw += val
        elif isinstance(val, dict):
            for sub_val in val.values():
                if isinstance(sub_val, (int, float)):
                    raw += sub_val

    if raw == 0:
        return 0.0, "Engagement metrics present but all zero"

    # Logarithmic scaling: engagement follows power-law distributions
    score = min(1.0, math.log1p(raw) / 10.0)
    return round(score, 3), f"Raw engagement sum: {raw:.0f} (log-scaled to {score:.3f})"


def score_recency(published_at: datetime | None, now: datetime | None = None) -> tuple[float, str]:
    """Score based on how recent the content is.

    Content within 24h scores highest, decays over 7 days.
    """
    if published_at is None:
        return 0.5, "No publication date — defaulting to 0.5"

    if now is None:
        now = datetime.now(timezone.utc)

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_hours = max(0, (now - published_at).total_seconds() / 3600)

    if age_hours <= 1:
        score = 1.0
    elif age_hours <= 24:
        score = 0.9 + 0.1 * (1 - age_hours / 24)
    elif age_hours <= 168:  # 7 days
        score = 0.5 * (1 - (age_hours - 24) / 144)
    else:
        score = 0.05

    return round(score, 3), f"Content is {age_hours:.1f}h old"


def score_cross_source(platform_count: int) -> tuple[float, str]:
    """Score based on how many distinct sources mention the same topic."""
    if platform_count <= 1:
        return 0.1, "Single source — no cross-platform signal"
    if platform_count == 2:
        return 0.5, "Appears on 2 sources"
    if platform_count == 3:
        return 0.8, "Appears on 3 sources"
    score = min(1.0, 0.8 + 0.05 * (platform_count - 3))
    return round(score, 3), f"Appears on {platform_count} distinct sources"


def score_novelty(item_count: int, avg_age_hours: float | None) -> tuple[float, str]:
    """Score based on novelty — fewer items from a topic = more novel."""
    if item_count <= 1:
        base = 1.0
    elif item_count <= 3:
        base = 0.7
    elif item_count <= 10:
        base = 0.4
    else:
        base = 0.2

    explanation = f"{item_count} source items for this topic"
    return round(base, 3), explanation


def score_momentum(
    engagement_list: list[dict[str, Any]],
    published_dates: list[datetime | None],
) -> tuple[float, str]:
    """Score momentum by detecting engagement concentration in recent items.

    If recent items have higher engagement than older ones, momentum
    is positive.
    """
    if not engagement_list:
        return 0.3, "Insufficient data for momentum — defaulting to 0.3"

    # Simple heuristic: count items with any engagement
    engaged = sum(
        1
        for e in engagement_list
        if any(isinstance(v, (int, float)) and v > 0 for v in e.values())
    )
    total = max(1, len(engagement_list))
    ratio = engaged / total

    score = min(1.0, ratio * 1.2)
    return round(score, 3), f"{engaged}/{total} items show engagement signals"


def compute_viral_score(
    engagement: dict[str, Any],
    published_at: datetime | None,
    source_count: int,
    item_count: int,
    engagement_list: list[dict[str, Any]] | None = None,
    published_dates: list[datetime | None] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute all scores for a viral idea.

    Returns a dict with individual scores, composite score, and evidence.
    """
    eng_score, eng_evidence = score_engagement(engagement)
    rec_score, rec_evidence = score_recency(published_at, now)
    cross_score, cross_evidence = score_cross_source(source_count)
    novel_score, novel_evidence = score_novelty(item_count, None)
    mom_score, mom_evidence = score_momentum(
        engagement_list or [engagement],
        published_dates or [published_at],
    )

    composite = (
        _WEIGHTS["engagement"] * eng_score
        + _WEIGHTS["recency"] * rec_score
        + _WEIGHTS["cross_source"] * cross_score
        + _WEIGHTS["novelty"] * novel_score
        + _WEIGHTS["momentum"] * mom_score
    )

    evidence = [
        f"Engagement: {eng_evidence}",
        f"Recency: {rec_evidence}",
        f"Cross-source: {cross_evidence}",
        f"Novelty: {novel_evidence}",
        f"Momentum: {mom_evidence}",
    ]

    return {
        "viral_score": round(composite, 3),
        "engagement_score": eng_score,
        "momentum_score": mom_score,
        "cross_source_score": cross_score,
        "novelty_score": novel_score,
        "evidence": evidence,
    }
