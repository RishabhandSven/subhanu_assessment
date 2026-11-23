import logging
import asyncio
from typing import Dict, Any, List, Optional
from decimal import Decimal
import config
from schema import (
    ShopifyOrderCreate,
    OrderLineItemCreate,
    FulfillmentStatus,
    FinancialStatus,
    AsyncJobPayload,
    WorkflowIdentifier,
)
from db_w1_pglite import w1_db
from db_w2_dataconnect import w2_db
from worker import w1_worker, record_log

logger = logging.getLogger("agent")

# --- Google ADK 2.0 Agent Initialization ---
try:
    import google.adk as adk
    HAS_GOOGLE_ADK = True
except ImportError:
    adk = None
    HAS_GOOGLE_ADK = False


# ==============================================================================
# 1. SHOPIFY SAMPLE / MOCK TOOLS
# ==============================================================================

def get_shopify_order(order_number: str) -> Dict[str, Any]:
    """
    Mock Shopify store tool: Fetches order and line items for an order reference.
    
    Args:
        order_number: Shopify order identifier (e.g. '#1001' or '1001')
    """
    clean_num = order_number.strip()
    if not clean_num.startswith("#"):
        clean_num = f"#{clean_num}"

    # Sample mock Shopify data store with parent-child line items
    sample_catalog = {
        "#1001": {
            "shopify_order_number": "#1001",
            "customer_name": "Eleanor Vance",
            "financial_status": "PAID",
            "fulfillment_status": "UNFULFILLED",
            "currency": "USD",
            "items": [
                {"sku": "SHOPIFY-HOODIE-M", "title": "Heavyweight Zip Hoodie (Medium)", "quantity": 1, "unit_price": 58.00},
                {"sku": "STICKER-PACK", "title": "Die-Cut Vinyl Stickers", "quantity": 3, "unit_price": 4.50}
            ]
        },
        "#1002": {
            "shopify_order_number": "#1002",
            "customer_name": "Marcus Kane",
            "financial_status": "PAID",
            "fulfillment_status": "FULFILLED",
            "currency": "USD",
            "items": [
                {"sku": "MUG-EMBER", "title": "Temperature Control Ceramic Mug", "quantity": 1, "unit_price": 129.00}
            ]
        }
    }

    if clean_num in sample_catalog:
        order = sample_catalog[clean_num]
        return {
            "status": "success",
            "source": "SHOPIFY_API_MOCK",
            "order": order
        }
    
    # Return dynamic fallback order if not in mock catalog
    return {
        "status": "success",
        "source": "SHOPIFY_API_MOCK",
        "order": {
            "shopify_order_number": clean_num,
            "customer_name": "Shopify Guest Customer",
            "financial_status": "PAID",
            "fulfillment_status": "UNFULFILLED",
            "currency": "USD",
            "items": [
                {"sku": "SAMPLE-SKU-1", "title": "Standard Store Item", "quantity": 1, "unit_price": 25.00}
            ]
        }
    }


def fulfill_shopify_line_items(order_number: str, line_item_skus: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Mock Shopify store tool: Updates fulfillment status on Shopify line items.
    
    Args:
        order_number: Shopify order reference (e.g. '#1001')
        line_item_skus: Optional list of specific SKUs to fulfill. If None, fulfills all items.
    """
    clean_num = order_number.strip()
    skus_fulfilled = line_item_skus or ["ALL_ITEMS"]
    
    return {
        "status": "success",
        "source": "SHOPIFY_API_MOCK",
        "action": "FULFILL_ITEMS",
        "shopify_order_number": clean_num,
        "fulfilled_skus": skus_fulfilled,
        "fulfillment_status": "FULFILLED",
        "message": f"Successfully fulfilled items {skus_fulfilled} for order {clean_num} on Shopify API."
    }


# ==============================================================================
# 2. WORKFLOW-AWARE TOOLS (WORKFLOW 1 & WORKFLOW 2)
# ==============================================================================

def workflow_1_sync_create_order(
    shopify_order_number: str,
    customer_name: str,
    items: List[Dict[str, Any]],
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Workflow 1 Tool (Sync): Creates an order with child line items directly in PGlite / local store.
    
    Args:
        shopify_order_number: External Shopify order reference (e.g. '#1001')
        customer_name: Full customer name
        items: List of line items with keys 'sku', 'title', 'quantity', 'unit_price'
        notes: Optional order notes
    """
    line_item_creates = [
        OrderLineItemCreate(
            sku=str(item.get("sku", "UNKNOWN")),
            title=str(item.get("title", "Item")),
            quantity=int(item.get("quantity", 1)),
            unit_price=Decimal(str(item.get("unit_price", "0.00")))
        )
        for item in items
    ]
    
    order_create = ShopifyOrderCreate(
        shopify_order_number=shopify_order_number,
        customer_name=customer_name,
        notes=notes,
        items=line_item_creates
    )
    
    saved_order = w1_db.create_order(order_create)
    record_log(
        workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
        action="SYNC_CREATE_ORDER",
        status="SUCCESS",
        details=f"Order {saved_order.id} with {len(saved_order.items)} line items written synchronously to PGlite/fallback.",
        order_id=saved_order.id
    )
    
    return {
        "status": "success",
        "workflow": WorkflowIdentifier.WORKFLOW_1_PGLITE.value,
        "mode": "SYNCHRONOUS_WRITE",
        "storage": w1_db.engine_type,
        "order": saved_order.model_dump(mode="json")
    }


def workflow_1_async_reconcile_order(order_id: str, target_status: str = "FULFILLED") -> Dict[str, Any]:
    """
    Workflow 1 Tool (Async): Enqueues a background reconciliation/fulfillment job to worker.py.
    
    Args:
        order_id: The local database order ID to reconcile
        target_status: Target status ('FULFILLED', 'IN_PROGRESS', etc.)
    """
    try:
        status_enum = FulfillmentStatus(target_status.upper())
    except ValueError:
        status_enum = FulfillmentStatus.FULFILLED

    job = AsyncJobPayload(
        order_id=order_id,
        target_status=status_enum,
        workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE
    )
    
    # Enqueue into async worker queue
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(w1_worker.enqueue_job(job))
    except RuntimeError:
        # Fallback if called outside active event loop
        asyncio.run(w1_worker.enqueue_job(job))
        
    return {
        "status": "queued",
        "workflow": WorkflowIdentifier.WORKFLOW_1_PGLITE.value,
        "mode": "ASYNCHRONOUS_QUEUE",
        "job_id": job.job_id,
        "order_id": order_id,
        "target_status": status_enum.value,
        "message": f"[WORKFLOW_1_WORKER] Job {job.job_id} enqueued for background processing."
    }


def workflow_1_get_order(order_id: str) -> Dict[str, Any]:
    """
    Workflow 1 Tool (Sync): Reads an order and child line items from PGlite / local store.
    """
    order = w1_db.get_order(order_id)
    if not order:
        return {
            "status": "not_found",
            "workflow": WorkflowIdentifier.WORKFLOW_1_PGLITE.value,
            "order_id": order_id
        }
    return {
        "status": "success",
        "workflow": WorkflowIdentifier.WORKFLOW_1_PGLITE.value,
        "mode": "SYNCHRONOUS_READ",
        "storage": w1_db.engine_type,
        "order": order.model_dump(mode="json")
    }


def workflow_2_create_order(
    shopify_order_number: str,
    customer_name: str,
    items: List[Dict[str, Any]],
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Workflow 2 Tool (Relational): Creates an order using the Firebase Data Connect relational adapter.
    """
    line_item_creates = [
        OrderLineItemCreate(
            sku=str(item.get("sku", "UNKNOWN")),
            title=str(item.get("title", "Item")),
            quantity=int(item.get("quantity", 1)),
            unit_price=Decimal(str(item.get("unit_price", "0.00")))
        )
        for item in items
    ]
    
    order_create = ShopifyOrderCreate(
        shopify_order_number=shopify_order_number,
        customer_name=customer_name,
        notes=notes,
        items=line_item_creates
    )
    
    saved_order = w2_db.insert_order(order_create)
    record_log(
        workflow=WorkflowIdentifier.WORKFLOW_2_DATA_CONNECT,
        action="DATA_CONNECT_INSERT",
        status="SUCCESS",
        details=f"Order {saved_order.id} inserted via Firebase Data Connect relational adapter.",
        order_id=saved_order.id
    )
    
    return {
        "status": "success",
        "workflow": WorkflowIdentifier.WORKFLOW_2_DATA_CONNECT.value,
        "mode": "FIREBASE_DATA_CONNECT_RELATIONAL",
        "project": w2_db.project_id,
        "service": w2_db.service_name,
        "order": saved_order.model_dump(mode="json")
    }


def workflow_2_query_orders() -> Dict[str, Any]:
    """
    Workflow 2 Tool (Relational): Queries all orders from Firebase Data Connect schema.
    """
    orders = w2_db.fetch_all_orders()
    return {
        "status": "success",
        "workflow": WorkflowIdentifier.WORKFLOW_2_DATA_CONNECT.value,
        "mode": "FIREBASE_DATA_CONNECT_QUERY",
        "count": len(orders),
        "orders": [o.model_dump(mode="json") for o in orders]
    }


# Toolset registry
ALL_TOOLS = [
    get_shopify_order,
    fulfill_shopify_line_items,
    workflow_1_sync_create_order,
    workflow_1_async_reconcile_order,
    workflow_1_get_order,
    workflow_2_create_order,
    workflow_2_query_orders,
]


# ==============================================================================
# 3. ROOT AGENT INSTANTIATION (GOOGLE ADK 2.0)
# ==============================================================================

def create_root_agent():
    """
    Initializes Google ADK 2.0 Agent with instructions and tools.
    """
    instruction = (
        "You are the Shopify Operations & Workflow Coordinator Agent. "
        "You handle Shopify store orders and route actions across two distinct backends:\n"
        "1. Workflow 1 (Local PGlite + async worker): Use for synchronous reads/writes "
        "and enqueueing async order reconciliations.\n"
        "2. Workflow 2 (Firebase Data Connect / Cloud SQL): Use for relational data patterns "
        "aligned with Firebase services.\n"
        "Always inform the user which workflow was selected and provide clear status summaries."
    )

    if HAS_GOOGLE_ADK and adk:
        # Use gemini-2.5-flash or default model with Google ADK
        model_name = "gemini-2.5-flash"
        agent = adk.Agent(
            name="ShopifyWorkflowAgent",
            description="Agent that coordinates Shopify order operations across Workflow 1 and Workflow 2.",
            instruction=instruction,
            tools=ALL_TOOLS,
            model=model_name
        )
        return agent
    else:
        logger.warning("google-adk package not found; root_agent running in mock mode.")
        return None


root_agent = create_root_agent()


# ==============================================================================
# 4. RUNNER & DETERMINISTIC DISPATCH HELPER
# ==============================================================================

async def run_agent_prompt(prompt: str) -> Dict[str, Any]:
    """
    Safe execution entry point for FastAPI endpoints.
    - If GOOGLE_API_KEY is configured and ADK runner is available, invokes LLM with tools.
    - If GOOGLE_API_KEY is missing/empty, executes deterministic tool routing to allow full MVP testing without crashing.
    """
    clean_prompt = prompt.strip()
    
    # Check if API Key is present
    has_key = bool(config.GOOGLE_API_KEY and config.GOOGLE_API_KEY.strip())
    
    if has_key and HAS_GOOGLE_ADK and root_agent is not None:
        try:
            # When Runner is ready and Key is set
            # ADK Runner execution
            runner = adk.Runner(agent=root_agent)
            response = await runner.run_async(clean_prompt)
            return {
                "status": "success",
                "mode": "GOOGLE_ADK_LLM",
                "agent_name": root_agent.name,
                "prompt": prompt,
                "response": str(response)
            }
        except Exception as e:
            logger.warning(f"ADK runner call failed ({e}); falling back to deterministic dispatcher.")

    # Safe deterministic tool-routing fallback
    prompt_lower = clean_prompt.lower()
    routed_tool = None
    tool_output = None
    explanation = ""

    if "w2" in prompt_lower or "workflow 2" in prompt_lower or "firebase" in prompt_lower or "cloud sql" in prompt_lower:
        routed_tool = "workflow_2_create_order"
        shopify_info = get_shopify_order("#1001")
        order_info = shopify_info["order"]
        tool_output = workflow_2_create_order(
            shopify_order_number=order_info["shopify_order_number"],
            customer_name=order_info["customer_name"],
            items=order_info["items"],
            notes=f"Created via ADK router from prompt: '{prompt}'"
        )
        explanation = "Routed to [Workflow 2: Firebase Data Connect Relational Adapter]."

    elif "async" in prompt_lower or "worker" in prompt_lower or "reconcile" in prompt_lower:
        routed_tool = "workflow_1_async_reconcile_order"
        # First ensure an order exists in W1
        orders = w1_db.list_orders()
        if not orders:
            s_order = get_shopify_order("#1001")["order"]
            created = w1_db.create_order(ShopifyOrderCreate(
                shopify_order_number=s_order["shopify_order_number"],
                customer_name=s_order["customer_name"],
                items=[OrderLineItemCreate(**i) for i in s_order["items"]]
            ))
            target_id = created.id
        else:
            target_id = orders[0].id
            
        tool_output = workflow_1_async_reconcile_order(target_id, target_status="FULFILLED")
        explanation = "Routed to [Workflow 1: Async Worker Queue via worker.py]."

    elif "shopify" in prompt_lower or "fetch" in prompt_lower:
        routed_tool = "get_shopify_order"
        num = "#1001" if "#1001" in prompt_lower or "1001" in prompt_lower else "#1002"
        tool_output = get_shopify_order(num)
        explanation = f"Routed to Shopify API Mock tool for order {num}."

    else:
        # Default: Workflow 1 Sync order creation
        routed_tool = "workflow_1_sync_create_order"
        shopify_info = get_shopify_order("#1001")
        order_info = shopify_info["order"]
        tool_output = workflow_1_sync_create_order(
            shopify_order_number=order_info["shopify_order_number"],
            customer_name=order_info["customer_name"],
            items=order_info["items"],
            notes=f"Sync order created via ADK coordinator for prompt: '{prompt}'"
        )
        explanation = "Routed to [Workflow 1: Synchronous PGlite/Local Store]."

    return {
        "status": "success",
        "mode": "GOOGLE_ADK_DETERMINISTIC_DISPATCH",
        "api_key_configured": has_key,
        "agent_name": "ShopifyWorkflowAgent (ADK 2.0)",
        "prompt": prompt,
        "selected_tool": routed_tool,
        "tool_output": tool_output,
        "message": explanation
    }
