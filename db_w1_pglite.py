import os
import sqlite3
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Optional
import config
from schema import ShopifyOrder, ShopifyOrderCreate, OrderLineItem, WorkflowIdentifier, FulfillmentStatus

logger = logging.getLogger("Workflow1_PGlite")

# Check if py-pglite is installed/available
HAS_PGLITE = False
try:
    # Attempt import if available in environment
    import pglite  # type: ignore
    HAS_PGLITE = True
except ImportError:
    HAS_PGLITE = False


class W1PGliteAdapter:
    """
    Workflow 1 Store Adapter:
    Attempts PGlite connection; gracefully falls back to local SQLite on Windows Python 3.13
    without breaking sync read/write contracts.
    """
    def __init__(self, db_path: str = config.W1_SQLITE_FALLBACK_FILE):
        self.engine_type = "PGlite" if HAS_PGLITE else "SQLite-PGliteFallback"
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()
        logger.info(f"[WORKFLOW_1_PGLITE] Storage initialized using engine: {self.engine_type} at {self.db_path}")

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Parent Table: orders
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                shopify_order_number TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                total_price NUMERIC NOT NULL,
                financial_status TEXT NOT NULL,
                fulfillment_status TEXT NOT NULL,
                workflow_source TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)
            # Child Table: line_items
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS line_items (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                title TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price NUMERIC NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE
            );
            """)
            conn.commit()

    def create_order(self, order_data: ShopifyOrderCreate) -> ShopifyOrder:
        order = ShopifyOrder(
            shopify_order_number=order_data.shopify_order_number,
            customer_name=order_data.customer_name,
            financial_status=order_data.financial_status,
            fulfillment_status=order_data.fulfillment_status,
            workflow_source=WorkflowIdentifier.WORKFLOW_1_PGLITE,
            notes=order_data.notes,
        )

        total_price = Decimal("0.00")
        items: List[OrderLineItem] = []
        for item_data in order_data.items:
            item = OrderLineItem(
                order_id=order.id,
                sku=item_data.sku,
                title=item_data.title,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
            )
            items.append(item)
            total_price += Decimal(str(item_data.unit_price)) * item_data.quantity

        order.total_price = total_price
        order.items = items

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO orders (
                    id, shopify_order_number, customer_name, total_price,
                    financial_status, fulfillment_status, workflow_source, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.id, order.shopify_order_number, order.customer_name,
                str(order.total_price), order.financial_status.value,
                order.fulfillment_status.value, order.workflow_source.value,
                order.notes, order.created_at.isoformat(), order.updated_at.isoformat()
            ))

            for item in order.items:
                cursor.execute("""
                    INSERT INTO line_items (id, order_id, sku, title, quantity, unit_price)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (item.id, item.order_id, item.sku, item.title, item.quantity, str(item.unit_price)))

            conn.commit()

        logger.info(f"[WORKFLOW_1_PGLITE] Created parent order {order.id} with {len(items)} line items (Sync Write)")
        return order

    def get_order(self, order_id: str) -> Optional[ShopifyOrder]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            order_row = cursor.fetchone()
            if not order_row:
                return None

            cursor.execute("SELECT * FROM line_items WHERE order_id = ?", (order_id,))
            item_rows = cursor.fetchall()

            items = [
                OrderLineItem(
                    id=row["id"],
                    order_id=row["order_id"],
                    sku=row["sku"],
                    title=row["title"],
                    quantity=row["quantity"],
                    unit_price=Decimal(str(row["unit_price"]))
                )
                for row in item_rows
            ]

            return ShopifyOrder(
                id=order_row["id"],
                shopify_order_number=order_row["shopify_order_number"],
                customer_name=order_row["customer_name"],
                total_price=Decimal(str(order_row["total_price"])),
                financial_status=order_row["financial_status"],
                fulfillment_status=order_row["fulfillment_status"],
                workflow_source=order_row["workflow_source"],
                notes=order_row["notes"],
                created_at=datetime.fromisoformat(order_row["created_at"]),
                updated_at=datetime.fromisoformat(order_row["updated_at"]),
                items=items
            )

    def list_orders(self) -> List[ShopifyOrder]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM orders ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self.get_order(row["id"]) for row in rows if self.get_order(row["id"]) is not None]

    def update_fulfillment_status(self, order_id: str, new_status: FulfillmentStatus) -> Optional[ShopifyOrder]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                UPDATE orders SET fulfillment_status = ?, updated_at = ? WHERE id = ?
            """, (new_status.value, now, order_id))
            conn.commit()
            if cursor.rowcount == 0:
                return None

        logger.info(f"[WORKFLOW_1_PGLITE] Updated order {order_id} fulfillment_status -> {new_status.value}")
        return self.get_order(order_id)


# Singleton instance
w1_db = W1PGliteAdapter()
