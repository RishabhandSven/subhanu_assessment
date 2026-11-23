from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid


class WorkflowIdentifier(str, Enum):
    WORKFLOW_1_PGLITE = "WORKFLOW_1_PGLITE"
    WORKFLOW_2_DATA_CONNECT = "WORKFLOW_2_DATA_CONNECT"


class FinancialStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"


# --- Child Entity: Order Line Item ---
class OrderLineItemBase(BaseModel):
    sku: str = Field(..., description="Stock keeping unit")
    title: str = Field(..., description="Item title/description")
    quantity: int = Field(default=1, ge=1, description="Quantity ordered")
    unit_price: Decimal = Field(..., ge=0, description="Price per unit")


class OrderLineItemCreate(OrderLineItemBase):
    pass


class OrderLineItem(OrderLineItemBase):
    id: str = Field(default_factory=lambda: f"item_{uuid.uuid4().hex[:8]}")
    order_id: str


# --- Parent Entity: Shopify Order ---
class ShopifyOrderBase(BaseModel):
    shopify_order_number: str = Field(..., description="Shopify external order reference (e.g. #1001)")
    customer_name: str = Field(..., description="Customer full name")
    financial_status: FinancialStatus = FinancialStatus.PAID
    fulfillment_status: FulfillmentStatus = FulfillmentStatus.UNFULFILLED
    notes: Optional[str] = None


class ShopifyOrderCreate(ShopifyOrderBase):
    items: List[OrderLineItemCreate] = Field(default_factory=list, description="Child line items")


class ShopifyOrder(ShopifyOrderBase):
    id: str = Field(default_factory=lambda: f"order_{uuid.uuid4().hex[:8]}")
    total_price: Decimal = Decimal("0.00")
    workflow_source: WorkflowIdentifier
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    items: List[OrderLineItem] = Field(default_factory=list)


# --- Workflow / Async Event Payloads ---
class AsyncJobPayload(BaseModel):
    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:8]}")
    order_id: str
    target_status: FulfillmentStatus = FulfillmentStatus.FULFILLED
    workflow: WorkflowIdentifier = WorkflowIdentifier.WORKFLOW_1_PGLITE
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowExecutionLog(BaseModel):
    id: str = Field(default_factory=lambda: f"log_{uuid.uuid4().hex[:6]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    workflow: WorkflowIdentifier
    action: str
    order_id: Optional[str] = None
    status: str
    details: str
