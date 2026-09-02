"""System monitoring API endpoints.

GET /api/v1/system/resource-status — current system metrics.
GET /api/v1/system/capacity-advisor — explainable capacity assessment.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.capacity_advisor import CapacityAdvisor
from app.services.resource_monitor import ResourceMonitor

router = APIRouter()

# Module-level singletons for the monitoring services.
# ResourceMonitor collects on each call; the history accumulates in-process.
_monitor = ResourceMonitor()
_advisor = CapacityAdvisor(_monitor)


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
