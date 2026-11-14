"""Order service (OMS). Postgres store and idempotent Create Order: Verified. Schema: Ours."""
import os

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel

app = FastAPI(title="order-service")

DDL = """
CREATE TABLE IF NOT EXISTS orders (
    order_id   text PRIMARY KEY,
    user_id    text NOT NULL,
    store_id   text NOT NULL,
    items      jsonb NOT NULL,
    amount     int NOT NULL,
    status     text NOT NULL DEFAULT 'CONFIRMED',
    created_at timestamptz NOT NULL DEFAULT now()
);
"""
_ready = False


def _conn():
    g = os.getenv
    return psycopg.connect(
        f"host={g('POSTGRES_HOST', 'localhost')} port={g('POSTGRES_PORT', '5433')} "
        f"user={g('POSTGRES_USER', 'zepto')} password={g('POSTGRES_PASSWORD', 'zepto_dev')} "
        f"dbname={g('POSTGRES_DB', 'zepto')} connect_timeout=3")


def ensure_schema():
    global _ready
    if not _ready:
        with _conn() as c:
            c.execute(DDL)
        _ready = True


class OrderReq(BaseModel):
    order_id: str
    user_id: str
    store_id: str
    items: list[dict]
    amount: int


@app.post("/v1/orders")
def create_order(req: OrderReq):
    ensure_schema()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO orders (order_id, user_id, store_id, items, amount) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (order_id) DO NOTHING",
            (req.order_id, req.user_id, req.store_id, Jsonb(req.items), req.amount))
        created = cur.rowcount == 1
    return {"orderId": req.order_id, "created": created, "status": "CONFIRMED"}


@app.get("/v1/orders/{order_id}")
def get_order(order_id: str):
    ensure_schema()
    with _conn() as c:
        r = c.execute("SELECT order_id, user_id, store_id, items, amount, status, created_at "
                      "FROM orders WHERE order_id=%s", (order_id,)).fetchone()
    if not r:
        raise HTTPException(404, "order not found")
    return {"orderId": r[0], "userId": r[1], "storeId": r[2], "items": r[3],
            "amount": r[4], "status": r[5], "createdAt": r[6].isoformat()}
