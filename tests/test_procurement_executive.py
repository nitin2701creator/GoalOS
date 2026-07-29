"""Behaviour tests for the Procurement executive."""

from app.executives import BaseExecutive, ExecutiveLoader
from app.executives.procurement import ProcurementExecutive


def test_supplier_onboarding_and_preferred_supplier_tracking() -> None:
    executive = ProcurementExecutive()
    supplier = executive.onboard_supplier(company_name="Acme", rating=4.5, preferred_supplier=True)

    assert supplier in executive.list_suppliers()
    assert executive.service.suppliers.preferred_suppliers() == (supplier,)
    assert executive.service.suppliers.supplier_summary()["average_rating"] == 4.5


def test_rfq_quote_comparison_ranks_by_price_then_supplier_quality() -> None:
    executive = ProcurementExecutive()
    preferred = executive.create_supplier(company_name="Preferred", rating=5, preferred_supplier=True)
    standard = executive.create_supplier(company_name="Standard", rating=2)
    rfq = executive.create_rfq(supplier_ids=[preferred.id, standard.id], items=["laptop"])
    executive.service.rfqs.submit_quote(rfq.id, standard.id, 100)
    executive.service.rfqs.submit_quote(rfq.id, preferred.id, 100)

    comparison = executive.compare_quotes(rfq.id)
    assert comparison[0]["supplier_id"] == preferred.id
    assert comparison[0]["rank"] == 1


def test_purchase_request_and_purchase_order_lifecycle() -> None:
    executive = ProcurementExecutive()
    request = executive.create_purchase_request(requester="Nitin", department="IT", items=["laptop"], estimated_cost=1200)
    assert executive.approve_purchase_request(request.id).status == "approved"
    order = executive.create_purchase_order(supplier="Acme", items=["laptop"], total_amount=1000)
    assert executive.approve_purchase_order(order.id).approval_status == "approved"
    assert executive.receive_goods(order.id).delivery_status == "received"


def test_kpis_dashboard_recommendations_and_alerts() -> None:
    executive = ProcurementExecutive()
    request = executive.create_purchase_request(requester="Nitin", department="IT", items=["monitor"], estimated_cost=500)
    executive.approve_purchase_request(request.id)
    order = executive.create_purchase_order(supplier="Acme", items=["monitor"], total_amount=400)
    executive.approve_purchase_order(order.id)

    dashboard = executive.procurement_dashboard()
    assert dashboard["kpis"]["procurement_savings"] == 100
    assert dashboard["kpis"]["purchase_orders_issued"] == 1
    assert executive.generate_recommendations()
    assert executive.get_alerts()


def test_runtime_registration_and_lifecycle() -> None:
    executive = ProcurementExecutive()
    assert isinstance(executive, BaseExecutive)
    executive.initialize()
    assert executive.health_check()
    loader = ExecutiveLoader()
    assert "Procurement" in loader.discover()
    assert isinstance(loader.load_executive("procurement"), ProcurementExecutive)
