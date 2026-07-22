"""RFQ and quote comparison operations."""

from __future__ import annotations

from .procurement_models import RFQ, Supplier
from .supplier_manager import SupplierManager


class RFQManager:
    def __init__(self, suppliers: SupplierManager | None = None) -> None:
        self._suppliers = suppliers or SupplierManager()
        self._rfqs: dict[str, RFQ] = {}
        self._quotes: dict[str, list[dict[str, object]]] = {}

    def create_rfq(self, rfq: RFQ | None = None, **data: object) -> RFQ:
        rfq = rfq or RFQ(**data)
        if not rfq.supplier_ids or not rfq.items:
            raise ValueError("RFQ requires suppliers and items")
        for supplier_id in rfq.supplier_ids:
            supplier = self._suppliers.get_supplier(supplier_id)
            if not supplier.active:
                raise ValueError(f"Supplier is inactive: {supplier_id}")
        self._rfqs[rfq.id] = rfq
        self._quotes[rfq.id] = []
        return rfq

    def submit_quote(self, rfq_id: str, supplier_id: str, price: float, **details: object) -> dict[str, object]:
        rfq = self.get_rfq(rfq_id)
        if supplier_id not in rfq.supplier_ids:
            raise ValueError("supplier was not invited to this RFQ")
        if price < 0:
            raise ValueError("quote price cannot be negative")
        quote = {"supplier_id": supplier_id, "price": float(price), **details}
        quotes = self._quotes[rfq_id]
        quotes[:] = [q for q in quotes if q["supplier_id"] != supplier_id]
        quotes.append(quote)
        return quote

    def compare_quotes(self, rfq_id: str) -> tuple[dict[str, object], ...]:
        quotes = self._quotes.get(rfq_id)
        if quotes is None:
            raise ValueError(f"Unknown RFQ: {rfq_id}")
        def score(quote: dict[str, object]) -> tuple[float, float, float]:
            supplier: Supplier = self._suppliers.get_supplier(str(quote["supplier_id"]))
            # Lower price wins; ratings and preferred status break close price ties.
            return (float(quote["price"]), -supplier.rating, -float(supplier.preferred_supplier))
        ranked = sorted(quotes, key=score)
        return tuple({**quote, "supplier": self._suppliers.get_supplier(str(quote["supplier_id"])), "rank": rank}
                     for rank, quote in enumerate(ranked, start=1))

    def best_quote(self, rfq_id: str) -> dict[str, object] | None:
        comparisons = self.compare_quotes(rfq_id)
        return comparisons[0] if comparisons else None

    def get_rfq(self, rfq_id: str) -> RFQ:
        try:
            return self._rfqs[rfq_id]
        except KeyError as exc:
            raise ValueError(f"Unknown RFQ: {rfq_id}") from exc

    def rfqs(self) -> tuple[RFQ, ...]:
        return tuple(self._rfqs.values())

    def response_rate(self) -> float:
        invitations = sum(len(rfq.supplier_ids) for rfq in self._rfqs.values())
        responses = sum(len(quotes) for quotes in self._quotes.values())
        return responses / invitations if invitations else 0.0
