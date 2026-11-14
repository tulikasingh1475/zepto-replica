"""Cart service. Design: Ours (Zepto's cart internals are not public).
Keyed by user + store; stock is checked against the inventory service."""
import os

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="cart-service")

DDL = """
CREATE TABLE IF NOT EXISTS cart_items (
    user_id  text NOT NULL,
    store_id text NOT NULL,
    sku      text NOT NULL,
    qty      int  NOT NULL CHECK (qty > 0),
    PRIMARY KEY (user_id, store_id, sku)
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


def http() -> httpx.Client:
    return httpx.Client(timeout=2.0)


def _u(name, default):
    return os.getenv(name, default)


class SetItem(BaseModel):
    store_id: str
    sku: str
    qty: int = Field(ge=0)  # 0 removes the item


@app.put("/v1/cart/{user_id}/items")
def set_item(user_id: str, req: SetItem):
    ensure_schema()
    if req.qty > 0:
        try:
            with http() as h:
                r = h.get(f"{_u('INVENTORY_URL', 'http://localhost:8003')}/v1/stock",
                          params={"store_id": req.store_id, "skus": req.sku})
                r.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, "inventory unavailable")
        rows = r.json()
        if not rows or rows[0]["available"] < req.qty:
            raise HTTPException(409, {"error": "insufficient_stock", "sku": req.sku})
    with _conn() as c:
        if req.qty == 0:
            c.execute("DELETE FROM cart_items WHERE user_id=%s AND store_id=%s AND sku=%s",
                      (user_id, req.store_id, req.sku))
        else:
            c.execute("INSERT INTO cart_items (user_id, store_id, sku, qty) VALUES (%s,%s,%s,%s) "
                      "ON CONFLICT (user_id, store_id, sku) DO UPDATE SET qty = EXCLUDED.qty",
                      (user_id, req.store_id, req.sku, req.qty))
    return {"ok": True}


@app.get("/v1/cart/{user_id}")
def get_cart(user_id: str, store_id: str, demand_level: str = "NORMAL"):
    ensure_schema()
    with _conn() as c:
        rows = c.execute("SELECT sku, qty FROM cart_items WHERE user_id=%s AND store_id=%s ORDER BY sku",
                         (user_id, store_id)).fetchall()
    if not rows:
        return {"userId": user_id, "storeId": store_id, "items": [],
                "subtotal": 0, "deliveryFee": 0, "total": 0}
    qty = dict(rows)
    try:
        with http() as h:
            cat = h.post(f"{_u('CATALOG_URL', 'http://localhost:8002')}/v1/products/batch",
                         json={"skus": list(qty)})
            cat.raise_for_status()
            items = [{"sku": p["sku"], "name": p["name"], "mrp": p["mrp"], "qty": qty[p["sku"]],
                      "lineTotal": p["mrp"] * qty[p["sku"]]} for p in cat.json()]
            subtotal = sum(i["lineTotal"] for i in items)
            q = h.post(f"{_u('PRICING_URL', 'http://localhost:8006')}/v1/quote",
                       json={"subtotal": subtotal, "demand_level": demand_level})
            q.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(503, "dependency unavailable")
    quote = q.json()
    return {"userId": user_id, "storeId": store_id, "items": items, "subtotal": subtotal,
            "deliveryFee": quote["deliveryFee"], "total": quote["total"]}


@app.delete("/v1/cart/{user_id}")
def clear_cart(user_id: str, store_id: str):
    ensure_schema()
    with _conn() as c:
        cur = c.execute("DELETE FROM cart_items WHERE user_id=%s AND store_id=%s", (user_id, store_id))
    return {"removed": cur.rowcount}
