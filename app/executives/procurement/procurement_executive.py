"""GoalOS Procurement executive."""

from __future__ import annotations

from typing import Any

from app.executives.base_executive import BaseExecutive
from app.executives.executive_models import ExecutiveAlert, ExecutiveKPI, ExecutivePriority, ExecutiveRecommendation, ExecutiveSummary

from .procurement_models import PurchaseOrder, PurchaseRequest, RFQ, Supplier
from .procurement_service import ProcurementService


class ProcurementExecutive(BaseExecutive):
    """Own supplier, sourcing, purchasing, and procurement reporting workflows."""

    def __init__(self, service: ProcurementService | None = None) -> None:
        super().__init__("Procurement", "Owns supplier relationships, sourcing, and purchasing operations.")
        self.service = service or ProcurementService()
        self._initialized = False

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._initialized = False

    def health_check(self) -> bool:
        return self._initialized

    def onboard_supplier(self, **data: object) -> Supplier:
        return self.create_supplier(**data)

    def create_supplier(self, supplier: Supplier | None = None, **data: object) -> Supplier:
        return self.service.suppliers.add_supplier(supplier, **data)

    def update_supplier(self, supplier_id: str, **changes: object) -> Supplier:
        return self.service.suppliers.update_supplier(supplier_id, **changes)

    def list_suppliers(self) -> tuple[Supplier, ...]:
        return self.service.suppliers.list_suppliers()

    def create_rfq(self, rfq: RFQ | None = None, **data: object) -> RFQ:
        return self.service.rfqs.create_rfq(rfq, **data)

    def compare_quotes(self, rfq_id: str) -> tuple[dict[str, object], ...]:
        return self.service.rfqs.compare_quotes(rfq_id)

    def create_purchase_request(self, request: PurchaseRequest | None = None, **data: object) -> PurchaseRequest:
        return self.service.create_purchase_request(request, **data)

    def approve_purchase_request(self, request_id: str) -> PurchaseRequest:
        return self.service.approve_purchase_request(request_id)

    def create_purchase_order(self, order: PurchaseOrder | None = None, **data: object) -> PurchaseOrder:
        return self.service.create_purchase_order(order, **data)

    def approve_purchase_order(self, order_id: str) -> PurchaseOrder:
        return self.service.approve_purchase_order(order_id)

    def receive_goods(self, order_id: str) -> PurchaseOrder:
        return self.service.receive_goods(order_id)

    def procurement_dashboard(self) -> dict[str, object]:
        return self.service.dashboard()

    def generate_recommendations(self) -> tuple[dict[str, str], ...]:
        return self.service.recommendations()

    def get_summary(self) -> ExecutiveSummary:
        data = self.service.suppliers.supplier_summary()
        return ExecutiveSummary(executive_name=self.name, title="Procurement overview", status="ready" if self._initialized else "not_initialized", metadata=data)

    def get_kpis(self) -> tuple[ExecutiveKPI, ...]:
        return tuple(ExecutiveKPI(title=name.replace("_", " ").title(), value=value) for name, value in self.service.kpis().items())

    def get_alerts(self) -> tuple[ExecutiveAlert, ...]:
        return tuple(ExecutiveAlert(title=alert["title"], severity=alert["severity"]) for alert in self.service.alerts())

    def get_priorities(self) -> tuple[ExecutivePriority, ...]:
        return tuple(ExecutivePriority(title=item["title"], priority=2) for item in self.generate_recommendations())

    def get_recommendations(self) -> tuple[ExecutiveRecommendation, ...]:
        return tuple(ExecutiveRecommendation(title=item["title"], description=item["action"]) for item in self.generate_recommendations())

    def execute(self, action: str, **kwargs: Any) -> Any:
        actions = {name: getattr(self, name) for name in (
            "onboard_supplier", "create_supplier", "update_supplier", "list_suppliers", "create_rfq", "compare_quotes",
            "create_purchase_request", "approve_purchase_request", "create_purchase_order", "approve_purchase_order",
            "receive_goods", "procurement_dashboard", "generate_recommendations")}
        try:
            return actions[action.strip().casefold()](**kwargs)
        except KeyError as exc:
            raise ValueError(f"Unsupported procurement action: {action}") from exc

    def supported_integrations(self) -> tuple[str, ...]:
        return ()
