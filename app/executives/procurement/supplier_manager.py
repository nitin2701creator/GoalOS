"""Supplier-focused state and scoring operations."""

from __future__ import annotations

from dataclasses import replace

from .procurement_models import Supplier


class SupplierManager:
    def __init__(self) -> None:
        self._suppliers: dict[str, Supplier] = {}

    def add_supplier(self, supplier: Supplier | None = None, **data: object) -> Supplier:
        supplier = supplier or Supplier(**data)
        if not supplier.company_name.strip():
            raise ValueError("supplier company_name is required")
        self._suppliers[supplier.id] = supplier
        return supplier

    def get_supplier(self, supplier_id: str) -> Supplier:
        try:
            return self._suppliers[supplier_id]
        except KeyError as exc:
            raise ValueError(f"Unknown supplier: {supplier_id}") from exc

    def update_supplier(self, supplier_id: str, **changes: object) -> Supplier:
        supplier = replace(self.get_supplier(supplier_id), **changes)
        self._suppliers[supplier_id] = supplier
        return supplier

    def deactivate_supplier(self, supplier_id: str) -> Supplier:
        return self.update_supplier(supplier_id, active=False, preferred_supplier=False)

    def score_supplier(self, supplier_id: str, rating: float) -> Supplier:
        if not 0 <= rating <= 5:
            raise ValueError("supplier rating must be between 0 and 5")
        return self.update_supplier(supplier_id, rating=float(rating))

    def preferred_suppliers(self) -> tuple[Supplier, ...]:
        return tuple(s for s in self.list_suppliers() if s.active and s.preferred_supplier)

    def list_suppliers(self) -> tuple[Supplier, ...]:
        return tuple(self._suppliers.values())

    def supplier_summary(self) -> dict[str, object]:
        suppliers = self.list_suppliers()
        active = [supplier for supplier in suppliers if supplier.active]
        return {
            "total_suppliers": len(suppliers),
            "active_suppliers": len(active),
            "preferred_suppliers": len(self.preferred_suppliers()),
            "average_rating": sum(s.rating for s in active) / len(active) if active else 0.0,
        }
