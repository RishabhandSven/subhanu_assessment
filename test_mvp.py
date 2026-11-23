import os
import time
import uuid
import asyncio
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from schema import (
    ShopifyOrderCreate,
    OrderLineItemCreate,
    FulfillmentStatus,
    WorkflowIdentifier,
    AsyncJobPayload,
)
from db_w1_pglite import W1PGliteAdapter
from db_w2_dataconnect import FirebaseDataConnectAdapter
from worker import Workflow1Worker, execution_logs
import agent
from app import app


# ---------------------------------------------------------------------------
# FIXTURES & ISOLATED ENVIRONMENT SETUP
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_w1_store():
    """Provides an isolated W1 adapter using a unique temporary file."""
    temp_path = os.path.abspath(f"./data/test_w1_{uuid.uuid4().hex[:8]}.db")
    adapter = W1PGliteAdapter(db_path=temp_path)
    yield adapter
    try:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    except OSError:
        pass


@pytest.fixture
def isolated_w2_store():
    """Provides an isolated W2 adapter using a unique temporary file."""
    temp_path = os.path.abspath(f"./data/test_w2_{uuid.uuid4().hex[:8]}.db")
    adapter = FirebaseDataConnectAdapter(db_path=temp_path)
    yield adapter
    try:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    except OSError:
        pass


@pytest.fixture
def test_client():
    """FastAPI TestClient with active lifespan (starts and stops w1_worker cleanly)."""
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# 1. PARENT-CHILD SCHEMA & WORKFLOW 1 SYNC (db_w1_pglite.py)
# ---------------------------------------------------------------------------

def test_w1_parent_child_order_creation_integrity(isolated_w1_store):
    """
    Verifies creation of a ShopifyOrder parent with multiple OrderLineItem children:
    - Verifies child items link via foreign key order_id.
    - Verifies total_price calculation integrity across line items.
    """
    order_data = ShopifyOrderCreate(
        shopify_order_number="#1010",
        customer_name="Diana Prince",
        notes="Urgent delivery",
        items=[
            OrderLineItemCreate(sku="HOODIE-M", title="Zip Hoodie", quantity=2, unit_price=Decimal("45.00")),
            OrderLineItemCreate(sku="MUG-BLK", title="Matte Mug", quantity=1, unit_price=Decimal("15.50")),
        ]
    )
    
    created_order = isolated_w1_store.create_order(order_data)
    
    assert created_order.id.startswith("order_")
    assert created_order.shopify_order_number == "#1010"
    assert created_order.customer_name == "Diana Prince"
    assert created_order.workflow_source == WorkflowIdentifier.WORKFLOW_1_PGLITE
    assert created_order.fulfillment_status == FulfillmentStatus.UNFULFILLED
    # 2 * 45.00 + 1 * 15.50 = 105.50
    assert created_order.total_price == Decimal("105.50")
    assert len(created_order.items) == 2
    
    # Verify child items link to parent order_id
    for item in created_order.items:
        assert item.order_id == created_order.id
        assert item.id.startswith("item_")

    # Fetch fresh from DB to verify sync read persistence
    fetched_order = isolated_w1_store.get_order(created_order.id)
    assert fetched_order is not None
    assert fetched_order.id == created_order.id
    assert len(fetched_order.items) == 2
    assert fetched_order.total_price == Decimal("105.50")


def test_w1_sync_update_and_listing(isolated_w1_store):
    """Verifies listing orders and updating fulfillment status synchronously."""
    order_data = ShopifyOrderCreate(
        shopify_order_number="#1011",
        customer_name="Bruce Wayne",
        items=[OrderLineItemCreate(sku="BAT-01", title="Batarang Replica", quantity=3, unit_price=Decimal("30.00"))]
    )
    created = isolated_w1_store.create_order(order_data)
    
    # Verify order appears in list
    orders = isolated_w1_store.list_orders()
    assert any(o.id == created.id for o in orders)
    
    # Update fulfillment status synchronously
    updated = isolated_w1_store.update_fulfillment_status(created.id, FulfillmentStatus.FULFILLED)
    assert updated is not None
    assert updated.fulfillment_status == FulfillmentStatus.FULFILLED
    assert updated.updated_at >= created.created_at


# ---------------------------------------------------------------------------
# 2. WORKFLOW 1 ASYNC WORKER (worker.py + /api/w1/orders/{order_id}/sync-async)
# ---------------------------------------------------------------------------

def test_w1_async_worker_lifecycle(isolated_w1_store, monkeypatch):
    """
    Tests Workflow1Worker queueing, execution, and log emission with [WORKFLOW_1_WORKER] prefix.
    """
    async def _run_worker_test():
        # Create an order in isolated store
        order_data = ShopifyOrderCreate(
            shopify_order_number="#1012",
            customer_name="Clark Kent",
            items=[OrderLineItemCreate(sku="GLASSES-01", title="Horn Rim Glasses", quantity=1, unit_price=Decimal("120.00"))]
        )
        created = isolated_w1_store.create_order(order_data)
        
        # Patch worker's database target to isolated_w1_store
        monkeypatch.setattr("worker.w1_db", isolated_w1_store)
        
        test_worker = Workflow1Worker()
        await test_worker.start()
        
        job = AsyncJobPayload(
            order_id=created.id,
            target_status=FulfillmentStatus.FULFILLED,
            workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE
        )
        job_id = await test_worker.enqueue_job(job)
        assert job_id.startswith("job_")
        
        # Wait for the async worker sleep (0.5s) + buffer
        await asyncio.sleep(0.7)
        await test_worker.stop()
        
        # Verify order status was updated asynchronously
        reconciled = isolated_w1_store.get_order(created.id)
        assert reconciled.fulfillment_status == FulfillmentStatus.FULFILLED
        
        # Verify [WORKFLOW_1_WORKER] appears in execution logs
        matching_logs = [
            log for log in execution_logs
            if log.order_id == created.id and "[WORKFLOW_1_WORKER]" in log.details
        ]
        assert len(matching_logs) > 0

    asyncio.run(_run_worker_test())


def test_api_w1_async_trigger_endpoint(test_client):
    """Tests the /api/w1/orders/{order_id}/sync-async HTTP endpoint."""
    # Create order first via API
    create_res = test_client.post("/api/w1/orders", json={
        "shopify_order_number": "#1013",
        "customer_name": "Barry Allen",
        "items": [{"sku": "BOOT-01", "title": "Speed Boots", "quantity": 1, "unit_price": "89.99"}]
    })
    assert create_res.status_code == 200
    order = create_res.json()
    order_id = order["id"]
    
    # Trigger async reconciliation
    async_res = test_client.post(f"/api/w1/orders/{order_id}/sync-async", json={"target_status": "FULFILLED"})
    assert async_res.status_code == 200
    data = async_res.json()
    assert data["status"] == "queued"
    assert data["workflow"] == "WORKFLOW_1_PGLITE"
    assert data["order_id"] == order_id
    
    # Allow background worker to complete
    time.sleep(0.7)
    
    # Check updated status via GET /api/orders
    get_res = test_client.get("/api/orders?workflow=w1")
    assert get_res.status_code == 200
    w1_orders = get_res.json()
    matched = next((o for o in w1_orders if o["id"] == order_id), None)
    assert matched is not None
    assert matched["fulfillment_status"] == "FULFILLED"


# ---------------------------------------------------------------------------
# 3. WORKFLOW 2 RELATIONAL ADAPTER (db_w2_dataconnect.py + /api/w2/orders)
# ---------------------------------------------------------------------------

def test_w2_data_connect_relational_adapter(isolated_w2_store):
    """
    Verifies FirebaseDataConnectAdapter inserts and queries parent-child orders
    independently from Workflow 1 with WORKFLOW_2_DATA_CONNECT attribution.
    """
    order_data = ShopifyOrderCreate(
        shopify_order_number="#2010",
        customer_name="Arthur Curry",
        items=[
            OrderLineItemCreate(sku="TRIDENT-01", title="Poseidon Trident", quantity=1, unit_price=Decimal("450.00")),
            OrderLineItemCreate(sku="SCALE-01", title="Armor Scale Polish", quantity=2, unit_price=Decimal("12.50")),
        ]
    )
    
    created = isolated_w2_store.insert_order(order_data)
    assert created.workflow_source == WorkflowIdentifier.WORKFLOW_2_DATA_CONNECT
    assert created.total_price == Decimal("475.00")
    assert len(created.items) == 2
    
    # Direct fetch
    fetched = isolated_w2_store.fetch_order(created.id)
    assert fetched is not None
    assert fetched.shopify_order_number == "#2010"
    assert fetched.workflow_source == WorkflowIdentifier.WORKFLOW_2_DATA_CONNECT
    assert len(fetched.items) == 2
    
    # Verify raw SQL execution pattern (Cloud SQL / Data Connect introspection)
    raw_results = isolated_w2_store.execute_sql_query(
        "SELECT id, total_price FROM fdc_orders WHERE id = ?", (created.id,)
    )
    assert len(raw_results) == 1
    assert str(raw_results[0]["total_price"]) == "475"


def test_api_w2_endpoint(test_client):
    """Tests POST /api/w2/orders endpoint and verify W2 workflow attribution."""
    res = test_client.post("/api/w2/orders", json={
        "shopify_order_number": "#2011",
        "customer_name": "Hal Jordan",
        "items": [{"sku": "RING-01", "title": "Power Battery Replica", "quantity": 1, "unit_price": "199.00"}]
    })
    assert res.status_code == 200
    order = res.json()
    assert order["workflow_source"] == "WORKFLOW_2_DATA_CONNECT"
    assert len(order["items"]) == 1
    assert order["items"][0]["sku"] == "RING-01"


# ---------------------------------------------------------------------------
# 4. FASTAPI ENDPOINTS & GOOGLE ADK 2.0 SAFE FALLBACK (app.py & agent.py)
# ---------------------------------------------------------------------------

def test_api_serves_single_page_ui(test_client):
    """Verifies GET / serves the interactive single-page dashboard HTML."""
    res = test_client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Shopify + Google ADK 2.0" in res.text
    assert "W1: PGlite + worker.py" in res.text
    assert "Firebase Data Connect" in res.text


def test_api_orders_filtering(test_client):
    """Verifies GET /api/orders filters correctly by w1, w2, and all."""
    res_all = test_client.get("/api/orders?workflow=all")
    assert res_all.status_code == 200
    orders_all = res_all.json()
    assert isinstance(orders_all, list)
    
    res_w1 = test_client.get("/api/orders?workflow=w1")
    assert res_w1.status_code == 200
    for o in res_w1.json():
        assert o["workflow_source"] == "WORKFLOW_1_PGLITE"
        
    res_w2 = test_client.get("/api/orders?workflow=w2")
    assert res_w2.status_code == 200
    for o in res_w2.json():
        assert o["workflow_source"] == "WORKFLOW_2_DATA_CONNECT"


def test_api_logs_contains_audit_trail(test_client):
    """Verifies GET /api/logs returns recent workflow actions and logs."""
    res = test_client.get("/api/logs?limit=20")
    assert res.status_code == 200
    logs = res.json()
    assert isinstance(logs, list)
    assert len(logs) > 0
    # Every log must have required fields
    for log in logs:
        assert "workflow" in log
        assert "action" in log
        assert "status" in log
        assert "details" in log


def test_adk_agent_safe_fallback_without_api_key(test_client, monkeypatch):
    """
    Verifies POST /api/agent/query runs safely when GOOGLE_API_KEY is missing/empty:
    - Never crashes or raises unhandled exceptions.
    - Routes deterministically to appropriate Shopify and workflow tools.
    - Returns structured workflow attribution.
    """
    # Ensure GOOGLE_API_KEY is empty
    monkeypatch.setattr(agent.config, "GOOGLE_API_KEY", "")
    
    # 1. Test Shopify mock fetch query
    res_shopify = test_client.post("/api/agent/query", json={"prompt": "Fetch Shopify order #1001"})
    assert res_shopify.status_code == 200
    data1 = res_shopify.json()
    assert data1["status"] == "success"
    assert data1["selected_tool"] == "get_shopify_order"
    assert data1["tool_output"]["status"] == "success"
    assert data1["tool_output"]["order"]["shopify_order_number"] == "#1001"
    
    # 2. Test Workflow 2 routing query
    res_w2 = test_client.post("/api/agent/query", json={"prompt": "Store this in Workflow 2 Firebase Data Connect"})
    assert res_w2.status_code == 200
    data2 = res_w2.json()
    assert data2["status"] == "success"
    assert data2["selected_tool"] == "workflow_2_create_order"
    assert data2["tool_output"]["workflow"] == "WORKFLOW_2_DATA_CONNECT"
    
    # 3. Test Workflow 1 async reconcile routing query
    res_w1_async = test_client.post("/api/agent/query", json={"prompt": "Trigger async worker reconciliation"})
    assert res_w1_async.status_code == 200
    data3 = res_w1_async.json()
    assert data3["status"] == "success"
    assert data3["selected_tool"] == "workflow_1_async_reconcile_order"
    assert data3["tool_output"]["mode"] == "ASYNCHRONOUS_QUEUE"
    assert data3["tool_output"]["workflow"] == "WORKFLOW_1_PGLITE"
