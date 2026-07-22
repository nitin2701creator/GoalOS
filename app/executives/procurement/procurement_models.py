"""Dataclasses used by the Procurement executive."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


def _id() -> str:
    return uuid4().hex


@dataclass
class Supplier:
    id: str = field(default_factory=_id)
    company_name: str = ""
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    category: str = ""
    rating: float = 0.0
    preferred_supplier: bool = False
    active: bool = True


@dataclass
class RFQ:
    id: str = field(default_factory=_id)
    supplier_ids: list[str] = field(default_factory=list)
    items: list[object] = field(default_factory=list)
    due_date: str | None = None
    status: str = "open"


@dataclass
class PurchaseRequest:
    id: str = field(default_factory=_id)
    requester: str = ""
    department: str = ""
    items: list[object] = field(default_factory=list)
    estimated_cost: float = 0.0
    status: str = "pending"


@dataclass
class PurchaseOrder:
    id: str = field(default_factory=_id)
    supplier: str = ""
    items: list[object] = field(default_factory=list)
    total_amount: float = 0.0
    approval_status: str = "pending"
    delivery_status: str = "pending"
