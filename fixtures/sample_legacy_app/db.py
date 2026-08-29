"""Database connection helper and queries for legacy order service."""

import sqlite3
from typing import List, Dict, Any
from models import OrderCreateRequest


def get_db_connection() -> sqlite3.Connection:
    """Provides connection to SQLite database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    """Initializes tables in database."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            status TEXT DEFAULT 'PENDING'
        )
    """)
    conn.commit()


def query_orders(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch orders with limit."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, customer_id, item_id, amount, currency, status FROM orders LIMIT ?", (limit,))
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def insert_order(conn: sqlite3.Connection, order_req: OrderCreateRequest) -> Dict[str, Any]:
    """Inserts a new order."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (customer_id, item_id, amount, currency, status) VALUES (?, ?, ?, ?, ?)",
        (order_req.customer_id, order_req.item_id, order_req.amount, order_req.currency, "CONFIRMED")
    )
    conn.commit()
    order_id = cursor.lastrowid
    return {
        "id": order_id,
        "customer_id": order_req.customer_id,
        "item_id": order_req.item_id,
        "amount": order_req.amount,
        "currency": order_req.currency,
        "status": "CONFIRMED"
    }
