"""Resource Guardian API endpoints.

GET /api/v1/resource-guardian/status — current capacity assessment
GET /api/v1/resource-guardian/alerts — recent capacity alerts
GET /api/v1/resource-guardian/health — quick health check
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.resource_guardian import ResourceGuardian

router = APIRouter()

# Module-level singleton
_guardian = ResourceGuardian()


@router.get("/status")
def guardian_status():
    """Return the full Resource Guardian capacity assessment."""
    assessment = _guardian.assess()
    return _guardian.to_dict(assessment)


@router.get("/alerts")
def guardian_alerts():
    """Return recent capacity alerts."""
    return {
        "alerts": _guardian.get_alerts(limit=50),
        "current_state": _guardian.current_state.value if _guardian.current_state else "UNKNOWN",
    }


@router.get("/health")
def guardian_health():
    """Quick health check — state only."""
    assessment = _guardian.assess()
    return {
        "state": assessment.state.value,
        "upgrade_required": assessment.upgrade_required,
        "score": assessment.score,
        "timestamp": assessment.timestamp,
    }


def get_guardian() -> ResourceGuardian:
    """Return the module-level ResourceGuardian instance."""
    return _guardian
