"""Business rules, reporting, and operational guidance for procurement."""

from __future__ import annotations

from .procurement_models import PurchaseOrder, PurchaseRequest
from .rfq_manager import RFQManager
from .supplier_manager import SupplierManager


class ProcurementService:
    def __init__(self, suppliers: SupplierManager | None = None, rfqs: RFQManager | None = None) -> None:
        self.suppliers = suppliers or SupplierManager()
        self.rfqs = rfqs or RFQManager(self.suppliers)
        self._purchase_requests: dict[str, PurchaseRequest] = {}
        self._purchase_orders: dict[str, PurchaseOrder] = {}

    def create_purchase_request(self, request: PurchaseRequest | None = None, **data: object) -> PurchaseRequest:
        request = request or PurchaseRequest(**data)
        if not request.requester.strip() or not request.items:
            raise ValueError("purchase request requires requester and items")
        if request.estimated_cost < 0:
            raise ValueError("estimated_cost cannot be negative")
        self._purchase_requests[request.id] = request
        return request

    def approve_purchase_request(self, request_id: str) -> PurchaseRequest:
        request = self._get_request(request_id)
        request.status = "approved"
        return request

    def create_purchase_order(self, order: PurchaseOrder | None = None, **data: object) -> PurchaseOrder:
        order = order or PurchaseOrder(**data)
        if not order.supplier.strip() or not order.items:
            raise ValueError("purchase order requires supplier and items")
        if order.total_amount < 0:
            raise ValueError("total_amount cannot be negative")
        self._purchase_orders[order.id] = order
        return order

    def approve_purchase_order(self, order_id: str) -> PurchaseOrder:
        order = self._get_order(order_id)
        order.approval_status = "approved"
        return order

    def receive_goods(self, order_id: str) -> PurchaseOrder:
        order = self._get_order(order_id)
        if order.approval_status != "approved":
            raise ValueError("purchase order must be approved before goods can be received")
        order.delivery_status = "received"
        return order

    def purchase_requests(self) -> tuple[PurchaseRequest, ...]:
        return tuple(self._purchase_requests.values())

    def purchase_orders(self) -> tuple[PurchaseOrder, ...]:
        return tuple(self._purchase_orders.values())

    def kpis(self) -> dict[str, float | int]:
        orders = self.purchase_orders()
        # Savings are recorded as the approved request estimate less PO spend.
        approved_estimate = sum(r.estimated_cost for r in self.purchase_requests() if r.status == "approved")
        issued_spend = sum(o.total_amount for o in orders if o.approval_status == "approved")
        summary = self.suppliers.supplier_summary()
        return {
            "procurement_savings": max(approved_estimate - issued_spend, 0.0),
            "average_supplier_rating": float(summary["average_rating"]),
            "rfqs_created": len(self.rfqs.rfqs()),
            "purchase_orders_issued": sum(o.approval_status == "approved" for o in orders),
            "supplier_response_rate": self.rfqs.response_rate(),
        }

    def alerts(self) -> tuple[dict[str, str], ...]:
        alerts: list[dict[str, str]] = []
        if not self.suppliers.preferred_suppliers():
            alerts.append({"title": "No preferred suppliers", "severity": "medium"})
        for order in self.purchase_orders():
            if order.approval_status == "pending":
                alerts.append({"title": f"Purchase order {order.id} awaits approval", "severity": "medium"})
        return tuple(alerts)

    def recommendations(self) -> tuple[dict[str, str], ...]:
        recommendations: list[dict[str, str]] = []
        if not self.suppliers.preferred_suppliers():
            recommendations.append({"title": "Establish preferred suppliers", "action": "review_supplier_scorecards"})
        if self.rfqs.rfqs() and self.rfqs.response_rate() < 0.5:
            recommendations.append({"title": "Improve supplier RFQ response", "action": "follow_up_on_open_rfqs"})
        if any(request.status == "pending" for request in self.purchase_requests()):
            recommendations.append({"title": "Review pending purchase requests", "action": "approve_purchase_requests"})
        return tuple(recommendations)

    def dashboard(self) -> dict[str, object]:
        return {
            "supplier_summary": self.suppliers.supplier_summary(),
            "kpis": self.kpis(),
            "purchase_requests": self.purchase_requests(),
            "purchase_orders": self.purchase_orders(),
            "alerts": self.alerts(),
            "recommendations": self.recommendations(),
        }

    def _get_request(self, request_id: str) -> PurchaseRequest:
        try:
            return self._purchase_requests[request_id]
        except KeyError as exc:
            raise ValueError(f"Unknown purchase request: {request_id}") from exc

    def _get_order(self, order_id: str) -> PurchaseOrder:
        try:
            return self._purchase_orders[order_id]
        except KeyError as exc:
            raise ValueError(f"Unknown purchase order: {order_id}") from exc
