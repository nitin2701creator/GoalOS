"""System monitoring API endpoints.

GET /api/v1/system/resource-status — current system metrics.
GET /api/v1/system/capacity-advisor — explainable capacity assessment.
GET /api/v1/system/guardian — Resource Guardian capacity assessment.
GET /api/v1/system/guardian/alerts — Resource Guardian alerts.
GET /api/v1/system/guardian/health — quick guardian health check.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.capacity_advisor import CapacityAdvisor
from app.services.resource_guardian import ResourceGuardian
from app.services.resource_monitor import ResourceMonitor

router = APIRouter()

# Module-level singletons for the monitoring services.
# ResourceMonitor collects on each call; the history accumulates in-process.
_monitor = ResourceMonitor()
_advisor = CapacityAdvisor(_monitor)
_guardian = ResourceGuardian(monitor=_monitor)


@router.get("/resource-status")
def resource_status():
    """Return current system resource metrics."""
    metrics = _monitor.collect()
    return {
        "status": "ok",
        "metrics": _monitor.to_dict(metrics),
        "sustained_averages": _monitor.get_sustained_averages(),
    }


@router.get("/capacity-advisor")
def capacity_advisor():
    """Return an explainable capacity assessment."""
    assessment = _advisor.assess()
    return {
        "status": assessment.status,
        "reasons": assessment.reasons,
        "sustained_metrics": assessment.sustained_metrics,
        "current_metrics": assessment.current_metrics,
        "recommended_plan": assessment.recommended_plan,
        "thresholds_applied": assessment.thresholds_applied,
    }


@router.get("/guardian")
def guardian_status():
    """Return the full Resource Guardian capacity assessment."""
    assessment = _guardian.assess()
    return _guardian.to_dict(assessment)


@router.get("/guardian/alerts")
def guardian_alerts():
    """Return recent capacity alerts from the Resource Guardian."""
    return {
        "alerts": _guardian.get_alerts(limit=50),
        "current_state": _guardian.current_state.value if _guardian.current_state else "UNKNOWN",
    }


@router.get("/guardian/health")
def guardian_health():
    """Quick Resource Guardian health check — state only."""
    assessment = _guardian.assess()
    return {
        "state": assessment.state.value,
        "upgrade_required": assessment.upgrade_required,
        "score": assessment.score,
        "timestamp": assessment.timestamp,
    }
