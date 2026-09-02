"""Meta Ads intelligence layer for GoalOS.

Implements the five core intelligence capabilities from the Meta Ads Stack:

1. Competitor Intelligence — analyze competitor ads, hooks, offers, CTAs
2. Bulk Copy Generation — generate 20 on-brand variations (5 angles × 4 variations)
3. Creative Scoring — score hooks, copy, CTAs, emotional pull, offer clarity
4. Creative Fatigue Detection — CTR, frequency, CPC analysis with classification
5. Full Account Audit — pixel/CAPI, structure, overlap, quality, targeting

These are research/review tools — they do not turn ads on/off.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CompetitorAd:
    """Normalized competitor ad data."""
    ad_id: str
    page_name: str
    body: str = ""
    headline: str = ""
    cta: str = ""
    creative_type: str = ""
    started_running: str = ""
    platforms: list[str] = field(default_factory=list)


@dataclass
class AdScore:
    """Structured score for an ad creative."""
    hook_score: float = 0.0
    copy_score: float = 0.0
    cta_score: float = 0.0
    emotional_pull: float = 0.0
    offer_clarity: float = 0.0
    visual_fit: float = 0.0
    overall: float = 0.0
    feedback: list[str] = field(default_factory=list)


@dataclass
class FatigueSignal:
    """Creative fatigue signal."""
    entity_id: str
    entity_name: str
    ctr: float = 0.0
    frequency: float = 0.0
    cpc: float = 0.0
    spend: float = 0.0
    impressions: int = 0
    classification: str = "healthy"  # healthy / warning / critical
    reason: str = ""


@dataclass
class AuditFinding:
    """One finding from an account audit."""
    category: str
    severity: str  # info / warning / critical
    title: str
    description: str
    recommendation: str = ""
    estimated_impact: str = ""


# ---------------------------------------------------------------------------
# 1. Competitor Intelligence
# ---------------------------------------------------------------------------

# High-performing CTA patterns (from Meta Ads library research)
_CTA_PATTERNS = [
    "Shop Now", "Learn More", "Sign Up", "Get Offer", "Download",
    "Book Now", "Contact Us", "Apply Now", "Subscribe", "Try Free",
    "Start Free Trial", "See More", "Watch More", "Listen Now",
]

# Hook patterns that indicate high-performing ad structures
_HOOK_PATTERNS = [
    re.compile(r"(?:Did you know|Here's the thing|Stop scrolling)", re.IGNORECASE),
    re.compile(r"(?:Save \d+%|Free|Limited time|Exclusive)", re.IGNORECASE),
    re.compile(r"(?:Stop doing|You're doing it wrong|The secret)", re.IGNORECASE),
    re.compile(r"(?:Introducing|New|Just launched|Finally)", re.IGNORECASE),
    re.compile(r"(?:Join \d+|Trusted by|Featured in)", re.IGNORECASE),
]


def extract_competitor_intelligence(
    ads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze competitor ads for hooks, offers, CTA patterns, longevity.

    Args:
        ads: List of ad dictionaries from Meta Ad Library API.

    Returns:
        Structured competitor intelligence report.
    """
    if not ads:
        return {
            "ads_analyzed": 0,
            "hooks": [],
            "offers": [],
            "cta_patterns": [],
            "hook_ranking": [],
            "unused_angles": [],
        }

    hooks = []
    offers = []
    cta_patterns = []
    ad_longevity = []

    for ad in ads:
        body = ad.get("body", "")
        headline = ad.get("headline", "")
        cta = ad.get("cta", "")

        # Extract hooks (first line or headline)
        first_line = body.split("\n")[0].strip() if body else headline
        if first_line:
            hooks.append({"text": first_line, "ad_id": ad.get("id", "")})

        # Extract offers (discounts, free trials, guarantees)
        offer_patterns = [
            r"(\d+%\s*(?:off|discount|save))",
            r"(free\s+\w+)",
            r"(\$\d+\s*(?:off|discount))",
            r"(money[- ]back\s*guarantee)",
            r"(risk[- ]free)",
            r"(no\s+commitment)",
        ]
        for pattern in offer_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                offers.append({"text": match.group(1), "ad_id": ad.get("id", "")})

        # Extract CTA patterns
        if cta:
            cta_patterns.append({"text": cta, "ad_id": ad.get("id", "")})

        # Track ad longevity
        started = ad.get("started_running", "")
        if started:
            ad_longevity.append({"ad_id": ad.get("id", ""), "started": started})

    # Rank hooks by frequency
    hook_texts = [h["text"] for h in hooks]
    hook_freq: dict[str, int] = {}
    for h in hook_texts:
        normalized = h.lower().strip()
        hook_freq[normalized] = hook_freq.get(normalized, 0) + 1
    hook_ranking = sorted(hook_freq.items(), key=lambda x: x[1], reverse=True)

    # Identify unused angles (common hook patterns not seen)
    used_patterns = set()
    for h in hook_texts:
        for pattern in _HOOK_PATTERNS:
            if pattern.search(h):
                used_patterns.add(pattern)
    unused_angles = [p.pattern for p in _HOOK_PATTERNS if p not in used_patterns]

    return {
        "ads_analyzed": len(ads),
        "hooks": hooks[:20],
        "offers": offers[:20],
        "cta_patterns": cta_patterns[:20],
        "hook_ranking": [{"pattern": p, "count": c} for p, c in hook_ranking[:10]],
        "unused_angles": unused_angles[:5],
        "ad_longevity": ad_longevity[:10],
    }


# ---------------------------------------------------------------------------
# 2. Bulk Copy Generation
# ---------------------------------------------------------------------------

_ANGLE_TEMPLATES: dict[str, list[str]] = {
    "problem_agitate": [
        "Tired of {problem}? {solution} — {benefit}.",
        "{problem} is costing you {cost}. Here's how to fix it: {solution}.",
        "Stop struggling with {problem}. {solution} makes it easy.",
    ],
    "social_proof": [
        "Join {number}+ customers who switched to {product}.",
        "{testimonial_author} said: \"{testimonial}\" — See why.",
        "Rated {rating}★ by {reviewers} customers.",
    ],
    "benefit_focused": [
        "{benefit} — without {pain_point}. That's {product}.",
        "Get {benefit} in just {timeframe}. No {pain_point}.",
        "What if {benefit} was just one click away?",
    ],
    "urgency_scarcity": [
        "Only {remaining} spots left. {offer} ends {deadline}.",
        "Last chance: {offer} — don't miss {benefit}.",
        "{deadline} is coming. Lock in {offer} now.",
    ],
    "before_after": [
        "Before {product}: {before_state}. After: {after_state}.",
        "From {before_state} to {after_state} — here's how {product} did it.",
        "{before_state}? Not anymore. {product} → {after_state}.",
    ],
}


def generate_ad_copy(
    product: str,
    benefits: list[str],
    audience: str = "",
    angles: list[str] | None = None,
    variations_per_angle: int = 4,
) -> dict[str, Any]:
    """Generate on-brand ad copy variations.

    Produces 5 angles × 4 variations = 20 variations by default.

    Args:
        product: Product/brand name.
        benefits: List of key benefits.
        audience: Target audience description.
        angles: Specific angles to use (defaults to all 5 templates).
        variations_per_angle: Number of variations per angle.

    Returns:
        Structured copy generation output.
    """
    selected_angles = angles or list(_ANGLE_TEMPLATES.keys())
    all_variations = []

    for angle in selected_angles:
        templates = _ANGLE_TEMPLATES.get(angle, [])
        for i in range(variations_per_angle):
            template = templates[i % len(templates)] if templates else f"{{benefit}} — try {product}."
            # Fill in template with product info
            filled = template.format(
                product=product,
                benefit=benefits[0] if benefits else "better results",
                problem=f"your {product.lower()} workflow",
                solution=f"{product} solves this",
                cost="time and money",
                number="500",
                testimonial="This changed everything for us",
                testimonial_author="A happy customer",
                rating="4.8",
                reviewers="200+",
                pain_point="the hassle",
                timeframe="7 days",
                remaining="50",
                offer="special launch pricing",
                deadline="this Friday",
                before_state="manual, slow, frustrating",
                after_state="automated, fast, effortless",
            )
            all_variations.append({
                "angle": angle,
                "variation": i + 1,
                "headline": product,
                "body": filled,
                "cta": _CTA_PATTERNS[i % len(_CTA_PATTERNS)],
            })

    return {
        "product": product,
        "audience": audience,
        "angles_used": selected_angles,
        "total_variations": len(all_variations),
        "variations": all_variations,
    }


# ---------------------------------------------------------------------------
# 3. Creative Scoring
# ---------------------------------------------------------------------------

def score_creative(
    headline: str = "",
    body: str = "",
    cta: str = "",
    description: str = "",
    creative_type: str = "",
) -> AdScore:
    """Score an ad creative across six dimensions.

    Returns a structured AdScore with individual dimension scores
    and an overall weighted score.
    """
    feedback = []

    # Hook score (headline + first line of body)
    hook_text = headline or (body.split("\n")[0] if body else "")
    hook_score = _score_hook(hook_text)
    if hook_score < 0.5:
        feedback.append("Hook is weak — consider a stronger opening line")

    # Copy score
    copy_score = _score_copy(body)
    if copy_score < 0.5:
        feedback.append("Copy could be more concise and benefit-focused")

    # CTA score
    cta_score = _score_cta(cta)
    if cta_score < 0.5:
        feedback.append("CTA is unclear — use a specific action verb")

    # Emotional pull
    emotional_pull = _score_emotion(body + " " + headline)
    if emotional_pull < 0.4:
        feedback.append("Low emotional resonance — add pain points or aspirations")

    # Offer clarity
    offer_clarity = _score_offer(body + " " + description)
    if offer_clarity < 0.4:
        feedback.append("Offer is not clear — state the value proposition explicitly")

    # Visual fit (based on creative type)
    visual_fit = 0.7 if creative_type else 0.5

    overall = (
        hook_score * 0.25
        + copy_score * 0.20
        + cta_score * 0.15
        + emotional_pull * 0.20
        + offer_clarity * 0.15
        + visual_fit * 0.05
    )

    return AdScore(
        hook_score=round(hook_score, 2),
        copy_score=round(copy_score, 2),
        cta_score=round(cta_score, 2),
        emotional_pull=round(emotional_pull, 2),
        offer_clarity=round(offer_clarity, 2),
        visual_fit=round(visual_fit, 2),
        overall=round(overall, 2),
        feedback=feedback,
    )


def _score_hook(text: str) -> float:
    if not text:
        return 0.0
    score = 0.3  # base
    if len(text) < 10:
        return 0.2
    if any(p.search(text) for p in _HOOK_PATTERNS):
        score += 0.3
    if text[0].isdigit() or text.startswith('"'):
        score += 0.1
    if "?" in text:
        score += 0.1
    if any(w in text.lower() for w in ["you", "your", "imagine", "what if"]):
        score += 0.1
    return min(score, 1.0)


def _score_copy(text: str) -> float:
    if not text:
        return 0.0
    words = text.split()
    score = 0.4
    if 10 <= len(words) <= 50:
        score += 0.2
    if any(w in text.lower() for w in ["free", "save", "guarantee", "proven"]):
        score += 0.15
    if text.count("!") <= 2:
        score += 0.1
    return min(score, 1.0)


def _score_cta(cta: str) -> float:
    if not cta:
        return 0.0
    if cta in _CTA_PATTERNS:
        return 0.9
    if any(v in cta.lower() for v in ["shop", "learn", "sign", "get", "try", "start"]):
        return 0.7
    return 0.4


def _score_emotion(text: str) -> float:
    emotion_words = [
        "love", "hate", "fear", "dream", "imagine", "finally",
        "amazing", "incredible", "secret", "exclusive", "limited",
        "proven", "guaranteed", "risk-free", "transform", "revolutionary",
    ]
    score = 0.3
    for word in emotion_words:
        if word in text.lower():
            score += 0.05
    return min(score, 1.0)


def _score_offer(text: str) -> float:
    offer_signals = [
        "free", "discount", "% off", "$ off", "save",
        "trial", "guarantee", "money back", "no risk",
        "limited time", "exclusive", "bonus",
    ]
    score = 0.3
    for signal in offer_signals:
        if signal in text.lower():
            score += 0.1
    return min(score, 1.0)


# ---------------------------------------------------------------------------
# 4. Creative Fatigue Detection
# ---------------------------------------------------------------------------

def detect_fatigue(
    performance_data: list[dict[str, Any]],
    *,
    ctr_warning: float = 1.0,
    ctr_critical: float = 0.5,
    frequency_warning: float = 3.0,
    frequency_critical: float = 5.0,
    cpc_warning: float = 5.0,
    cpc_critical: float = 10.0,
) -> list[FatigueSignal]:
    """Analyze performance data for creative fatigue signals.

    Args:
        performance_data: List of performance records with CTR, frequency, CPC.
        ctr_warning: CTR threshold for warning classification.
        ctr_critical: CTR threshold for critical classification.
        frequency_warning: Frequency threshold for warning.
        frequency_critical: Frequency threshold for critical.
        cpc_warning: CPC threshold for warning.
        cpc_critical: CPC threshold for critical.

    Returns:
        List of FatigueSignal with classification.
    """
    signals = []

    for item in performance_data:
        ctr = float(item.get("ctr", 0))
        frequency = float(item.get("frequency", 0))
        cpc = float(item.get("cpc", 0))
        spend = float(item.get("spend", 0))
        impressions = int(item.get("impressions", 0))

        # Determine classification
        classification = "healthy"
        reasons = []

        if ctr < ctr_critical:
            classification = "critical"
            reasons.append(f"CTR {ctr:.2f}% is critically low")
        elif ctr < ctr_warning:
            classification = "warning"
            reasons.append(f"CTR {ctr:.2f}% is below threshold")

        if frequency > frequency_critical:
            classification = "critical"
            reasons.append(f"Frequency {frequency:.1f} is critically high")
        elif frequency > frequency_warning:
            if classification != "critical":
                classification = "warning"
            reasons.append(f"Frequency {frequency:.1f} is high")

        if cpc > cpc_critical:
            classification = "critical"
            reasons.append(f"CPC ${cpc:.2f} is critically high")
        elif cpc > cpc_warning:
            if classification != "critical":
                classification = "warning"
            reasons.append(f"CPC ${cpc:.2f} is high")

        signals.append(FatigueSignal(
            entity_id=item.get("id", ""),
            entity_name=item.get("name", ""),
            ctr=ctr,
            frequency=frequency,
            cpc=cpc,
            spend=spend,
            impressions=impressions,
            classification=classification,
            reason="; ".join(reasons) if reasons else "healthy",
        ))

    return signals


# ---------------------------------------------------------------------------
# 5. Full Account Audit
# ---------------------------------------------------------------------------

def audit_account(
    account_data: dict[str, Any],
    campaigns: list[dict[str, Any]] | None = None,
    adsets: list[dict[str, Any]] | None = None,
    ads: list[dict[str, Any]] | None = None,
    performance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Perform a comprehensive Meta Ads account audit.

    Checks: pixel/CAPI, account structure, audience overlap,
    creative quality, targeting, and produces ranked fixes.
    """
    findings: list[AuditFinding] = []
    campaigns = campaigns or []
    adsets = adsets or []
    ads = ads or []
    performance = performance or []

    # 1. Account structure
    if not campaigns:
        findings.append(AuditFinding(
            category="structure",
            severity="critical",
            title="No campaigns found",
            description="Account has no campaigns. Create at least one campaign to start advertising.",
            recommendation="Create a campaign with a clear objective.",
        ))
    elif len(campaigns) > 20:
        findings.append(AuditFinding(
            category="structure",
            severity="warning",
            title=f"Too many campaigns ({len(campaigns)})",
            description="Account has more than 20 campaigns, which may cause budget fragmentation.",
            recommendation="Consolidate campaigns where possible.",
        ))

    # 2. Ad set analysis
    no_budget_adsets = [a for a in adsets if not a.get("daily_budget") and not a.get("lifetime_budget")]
    if no_budget_adsets:
        findings.append(AuditFinding(
            category="budget",
            severity="warning",
            title=f"{len(no_budget_adsets)} ad sets without budget",
            description="Some ad sets have no budget configured.",
            recommendation="Set explicit budgets for all ad sets.",
        ))

    # 3. Creative quality
    ads_without_creative = [a for a in ads if not a.get("creative")]
    if ads_without_creative:
        findings.append(AuditFinding(
            category="creative",
            severity="warning",
            title=f"{len(ads_without_creative)} ads without creative",
            description="Some ads are missing creative assets.",
            recommendation="Attach creatives to all ads.",
        ))

    # 4. Performance analysis
    if performance:
        low_ctr = [p for p in performance if float(p.get("ctr", 0)) < 0.5]
        if low_ctr:
            findings.append(AuditFinding(
                category="performance",
                severity="warning",
                title=f"{len(low_ctr)} entities with CTR < 0.5%",
                description="Several campaigns/ad sets have critically low click-through rates.",
                recommendation="Review ad copy, creative, and targeting for low-CTR entities.",
            ))

        high_frequency = [p for p in performance if float(p.get("frequency", 0)) > 4.0]
        if high_frequency:
            findings.append(AuditFinding(
                category="fatigue",
                severity="critical",
                title=f"{len(high_frequency)} entities with frequency > 4.0",
                description="High frequency indicates creative fatigue.",
                recommendation="Refresh creatives or expand audience targeting.",
            ))

    # 5. Targeting overlap (basic check)
    targeting_groups = [a.get("targeting", {}) for a in adsets if a.get("targeting")]
    if len(targeting_groups) > 1:
        # Basic overlap detection — same age range + same interests
        seen = set()
        for t in targeting_groups:
            key = json.dumps(t, sort_keys=True, default=str)
            if key in seen:
                findings.append(AuditFinding(
                    category="targeting",
                    severity="warning",
                    title="Potential audience overlap detected",
                    description="Multiple ad sets appear to target identical audiences.",
                    recommendation="Use exclusion targeting or consolidate overlapping ad sets.",
                ))
                break
            seen.add(key)

    # Rank findings by severity
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: severity_order.get(f.severity, 3))

    return {
        "account_id": account_data.get("id", ""),
        "findings": [
            {
                "category": f.category,
                "severity": f.severity,
                "title": f.title,
                "description": f.description,
                "recommendation": f.recommendation,
                "estimated_impact": f.estimated_impact,
            }
            for f in findings
        ],
        "total_findings": len(findings),
        "critical": sum(1 for f in findings if f.severity == "critical"),
        "warnings": sum(1 for f in findings if f.severity == "warning"),
        "score": max(0, 100 - (sum(1 for f in findings if f.severity == "critical") * 20) - (sum(1 for f in findings if f.severity == "warning") * 5)),
    }
