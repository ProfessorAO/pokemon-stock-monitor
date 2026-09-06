from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_db_path: str = "data/stock_monitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    retailer TEXT NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    release_date_text TEXT,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (retailer, sku)
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer TEXT NOT NULL,
    sku TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    available INTEGER NOT NULL,
    price REAL,
    error TEXT,
    FOREIGN KEY (retailer, sku) REFERENCES products (retailer, sku)
);

CREATE INDEX IF NOT EXISTS idx_observations_product_time
    ON observations (retailer, sku, observed_at DESC);
"""


def init_db(database_path: str) -> None:
    global _db_path
    _db_path = database_path
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def _connect():
    conn = sqlite3.connect(_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_product(retailer: str, sku: str) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM products WHERE retailer = ? AND sku = ?", (retailer, sku)
        )
        return cur.fetchone()


def upsert_product(retailer: str, sku: str, name: str, url: str, release_date_text: Optional[str]) -> bool:
    """Returns True if this is a brand-new product."""
    with _lock, _connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM products WHERE retailer = ? AND sku = ?", (retailer, sku)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE products SET name = ?, url = ?, release_date_text = COALESCE(?, release_date_text) "
                "WHERE retailer = ? AND sku = ?",
                (name, url, release_date_text, retailer, sku),
            )
            return False
        conn.execute(
            "INSERT INTO products (retailer, sku, name, url, release_date_text, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (retailer, sku, name, url, release_date_text, _now()),
        )
        return True


def get_last_observation(retailer: str, sku: str) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM observations WHERE retailer = ? AND sku = ? "
            "ORDER BY observed_at DESC LIMIT 1",
            (retailer, sku),
        )
        return cur.fetchone()


def insert_observation(retailer: str, sku: str, available: bool, price: Optional[float], error: Optional[str]) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO observations (retailer, sku, observed_at, available, price, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (retailer, sku, _now(), int(available), price, error),
        )


def list_latest_status() -> list[dict]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT p.retailer, p.sku, p.name, p.url, p.release_date_text, p.first_seen_at,
                   o.observed_at, o.available, o.price, o.error
            FROM products p
            LEFT JOIN observations o ON o.id = (
                SELECT id FROM observations
                WHERE retailer = p.retailer AND sku = p.sku
                ORDER BY observed_at DESC LIMIT 1
            )
            ORDER BY o.observed_at IS NULL, o.observed_at DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def list_known_products(retailer: str) -> list[sqlite3.Row]:
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM products WHERE retailer = ?", (retailer,))
        return cur.fetchall()
