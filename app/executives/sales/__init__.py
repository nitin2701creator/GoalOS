"""Sales executive package."""

from app.executives.sales.sales_executive import SalesExecutive
from app.executives.sales.sales_models import (
    SalesIntegrationHook,
    SalesKPI,
    SalesSummary,
)
from app.executives.sales.sales_service import SalesService

__all__ = [
    "SalesExecutive",
    "SalesIntegrationHook",
    "SalesKPI",
    "SalesService",
    "SalesSummary",
]
