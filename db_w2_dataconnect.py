from abc import ABC, abstractmethod
import sqlite3
import os
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Optional
import config
from schema import ShopifyOrder, ShopifyOrderCreate, OrderLineItem, WorkflowIdentifier, FulfillmentStatus

logger = logging.getLogger("Workflow2_DataConnect")


class RelationalStoreAdapter(ABC):
    """
    Abstract interface for relational PostgreSQL / Cloud SQL / Firebase SQL Connect data patterns.
    """
    @abstractmethod
    def insert_order(self, order_data: ShopifyOrderCreate) -> ShopifyOrder:
        pass

    @abstractmethod
    def fetch_order(self, order_id: str) -> Optional[ShopifyOrder]:
        pass

    @abstractmethod
    def fetch_all_orders(self) -> List[ShopifyOrder]:
        pass

    @abstractmethod
    def execute_sql_query(self, query: str, params: tuple = ()) -> List[dict]:
        pass


class FirebaseDataConnectAdapter(RelationalStoreAdapter):
    """
    Workflow 2 Adapter:
    Connects relational PostgreSQL / Cloud SQL data patterns cleanly alongside Workflow 1.
    Adheres to Firebase Data Connect query patterns and schema conventions.
    """
    def __init__(self, db_path: str = config.W2_SQLITE_FALLBACK_FILE):
        self.project_id = config.FIREBASE_PROJECT_ID
        self.service_name = config.FIREBASE_DATA_CONNECT_SERVICE
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_schema()
        logger.info(
            f"[WORKFLOW_2_DATA_CONNECT] Initialized for Firebase Project: '{self.project_id}' "
            f"Service: '{self.service_name}' using relational store at {self.db_path}"
        )

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Firebase Data Connect modeled parent table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS fdc_orders (
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
            # Firebase Data Connect modeled child table (1-to-many)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS fdc_line_items (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                title TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price NUMERIC NOT NULL,
                FOREIGN KEY (order_id) REFERENCES fdc_orders (id) ON DELETE CASCADE
            );
            """)
            conn.commit()

    def insert_order(self, order_data: ShopifyOrderCreate) -> ShopifyOrder:
        order = ShopifyOrder(
            shopify_order_number=order_data.shopify_order_number,
            customer_name=order_data.customer_name,
            financial_status=order_data.financial_status,
            fulfillment_status=order_data.fulfillment_status,
            workflow_source=WorkflowIdentifier.WORKFLOW_2_DATA_CONNECT,
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
                INSERT INTO fdc_orders (
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
                    INSERT INTO fdc_line_items (id, order_id, sku, title, quantity, unit_price)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (item.id, item.order_id, item.sku, item.title, item.quantity, str(item.unit_price)))

            conn.commit()

        logger.info(
            f"[WORKFLOW_2_DATA_CONNECT] Saved parent order {order.id} with {len(items)} items "
            f"via Firebase SQL Connect schema"
        )
        return order

    def fetch_order(self, order_id: str) -> Optional[ShopifyOrder]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM fdc_orders WHERE id = ?", (order_id,))
            order_row = cursor.fetchone()
            if not order_row:
                return None

            cursor.execute("SELECT * FROM fdc_line_items WHERE order_id = ?", (order_id,))
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

    def fetch_all_orders(self) -> List[ShopifyOrder]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM fdc_orders ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self.fetch_order(row["id"]) for row in rows if self.fetch_order(row["id"]) is not None]

    def execute_sql_query(self, query: str, params: tuple = ()) -> List[dict]:
        """Custom SQL query execution simulating Cloud SQL / Data Connect introspection."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


# Singleton instance
w2_db = FirebaseDataConnectAdapter()
