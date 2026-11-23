import os
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
from schema import (
    ShopifyOrder,
    ShopifyOrderCreate,
    AsyncJobPayload,
    FulfillmentStatus,
    WorkflowExecutionLog,
    WorkflowIdentifier,
)
from db_w1_pglite import w1_db
from db_w2_dataconnect import w2_db
from worker import w1_worker, execution_logs, record_log
from agent import run_agent_prompt


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start Workflow 1 Async Background Worker
    await w1_worker.start()
    record_log(
        workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
        action="APP_STARTUP",
        status="SUCCESS",
        details="FastAPI server initialized; Workflow 1 async worker listening."
    )
    yield
    # Shutdown: Cleanly stop background worker
    await w1_worker.stop()


app = FastAPI(
    title="Shopify + Google ADK 2.0 MVP",
    description="Dual Workflow Architecture (Workflow 1: PGlite + Worker, Workflow 2: Firebase SQL Connect)",
    version="1.0.0",
    lifespan=lifespan
)

# Resolve static directory relative to this file location for cloud deployment
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
INDEX_HTML = os.path.join(STATIC_DIR, "index.html")
ASSETS_DIR = os.path.join(STATIC_DIR, "assets")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/", response_class=FileResponse)
async def serve_index():
    return FileResponse(INDEX_HTML)


# ==============================================================================
# 1. UNIFIED & WORKFLOW-SPECIFIC ORDER ENDPOINTS
# ==============================================================================

@app.get("/api/orders", response_model=List[ShopifyOrder])
async def list_orders(workflow: Optional[str] = Query("all", pattern="^(w1|w2|all)$")):
    """
    Returns parent orders with nested child line items.
    Filters by Workflow 1 (PGlite), Workflow 2 (Data Connect), or all.
    """
    results: List[ShopifyOrder] = []
    if workflow in ("w1", "all"):
        results.extend(w1_db.list_orders())
    if workflow in ("w2", "all"):
        results.extend(w2_db.fetch_all_orders())

    # Sort descending by updated/created timestamp
    results.sort(key=lambda o: o.created_at, reverse=True)
    return results


@app.post("/api/w1/orders", response_model=ShopifyOrder)
async def create_w1_order_sync(payload: ShopifyOrderCreate):
    """
    Workflow 1 (Sync): Creates an order + line items immediately in PGlite/fallback store.
    """
    order = w1_db.create_order(payload)
    record_log(
        workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
        action="API_W1_SYNC_CREATE",
        status="SUCCESS",
        details=f"Order {order.id} ({order.shopify_order_number}) with {len(order.items)} items written to PGlite store.",
        order_id=order.id
    )
    return order


class AsyncTriggerRequest(BaseModel):
    target_status: FulfillmentStatus = FulfillmentStatus.FULFILLED


@app.post("/api/w1/orders/{order_id}/sync-async")
async def trigger_w1_async_update(order_id: str, body: AsyncTriggerRequest = AsyncTriggerRequest()):
    """
    Workflow 1 (Async): Enqueues a background reconciliation/fulfillment job to worker.py
    which updates PGlite asynchronously and logs [WORKFLOW_1_WORKER] execution events.
    """
    existing_order = w1_db.get_order(order_id)
    if not existing_order:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found in Workflow 1 store")

    job = AsyncJobPayload(
        order_id=order_id,
        target_status=body.target_status,
        workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE
    )
    job_id = await w1_worker.enqueue_job(job)

    return {
        "status": "queued",
        "workflow": WorkflowIdentifier.WORKFLOW_1_PGLITE.value,
        "job_id": job_id,
        "order_id": order_id,
        "target_status": body.target_status.value,
        "message": f"[WORKFLOW_1_WORKER] Background job {job_id} queued to update order {order_id}"
    }


@app.post("/api/w2/orders", response_model=ShopifyOrder)
async def create_w2_order_dataconnect(payload: ShopifyOrderCreate):
    """
    Workflow 2: Inserts relational order + line items via Firebase SQL Connect / Data Connect pattern.
    """
    order = w2_db.insert_order(payload)
    record_log(
        workflow=WorkflowIdentifier.WORKFLOW_2_DATA_CONNECT,
        action="API_W2_INSERT",
        status="SUCCESS",
        details=f"Order {order.id} ({order.shopify_order_number}) stored via Firebase Data Connect relational adapter.",
        order_id=order.id
    )
    return order


# ==============================================================================
# 2. GOOGLE ADK 2.0 AGENT QUERY ENDPOINT
# ==============================================================================

class AgentQueryRequest(BaseModel):
    prompt: str


@app.post("/api/agent/query")
async def query_agent(request: AgentQueryRequest):
    """
    Calls Google ADK 2.0 root_agent. Empty-key safe: falls back gracefully to deterministic
    tool router if GOOGLE_API_KEY is not configured yet.
    """
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    response = await run_agent_prompt(request.prompt)
    return response


# ==============================================================================
# 3. LIVE WORKFLOW LOGS AUDIT TRAIL
# ==============================================================================

@app.get("/api/logs", response_model=List[WorkflowExecutionLog])
async def get_logs(limit: int = 50):
    """
    Returns recent workflow execution logs so the UI can visibly trace which workflow handled what.
    """
    return execution_logs[:limit]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=config.APP_HOST, port=config.APP_PORT, reload=config.DEBUG)
