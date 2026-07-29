from pydantic import BaseModel

class PurchaseOrderRequest(BaseModel):
    order_id: str
    amount: float
    vendor: str
