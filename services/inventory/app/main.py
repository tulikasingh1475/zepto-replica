"""Inventory service. Reservation design: Ours (Zepto's is not public)."""
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(title="inventory-service")

DDL = """
CREATE TABLE IF NOT EXISTS stock (
    store_id  text NOT NULL,
    sku       text NOT NULL,
    available int  NOT NULL CHECK (available >= 0),
    reserved  int  NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    PRIMARY KEY (store_id, sku)
);
CREATE TABLE IF NOT EXISTS reservations (
    id         bigserial PRIMARY KEY,
    order_ref  text NOT NULL,
    store_id   text NOT NULL,
    sku        text NOT NULL,
    qty        int  NOT NULL CHECK (qty > 0),
    status     text NOT NULL,
    expires_at timestamptz NOT NULL,
    UNIQUE (order_ref, store_id, sku)
);
"""
_schema_ready = False


def _dsn() -> str:
    g = os.getenv
    return (f"host={g('POSTGRES_HOST', 'localhost')} port={g('POSTGRES_PORT', '5433')} "
            f"user={g('POSTGRES_USER', 'zepto')} password={g('POSTGRES_PASSWORD', 'zepto_dev')} "
            f"dbname={g('POSTGRES_DB', 'zepto')} connect_timeout=3")


def _conn():
    return psycopg.connect(_dsn())


def ensure_schema():
    global _schema_ready
    if not _schema_ready:
        with _conn() as c:
            c.execute(DDL)
        _schema_ready = True


class Item(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class ReserveRequest(BaseModel):
    order_ref: str
    store_id: str
    items: list[Item] = Field(min_length=1)
    ttl_seconds: int = Field(600, gt=0)


class ReleaseRequest(BaseModel):
    order_ref: str


@app.get("/v1/stock")
def get_stock(store_id: str, skus: str = Query(..., description="comma-separated")):
    ensure_schema()
    sku_list = [s for s in skus.split(",") if s]
    with _conn() as c:
        rows = c.execute(
            "SELECT sku, available, reserved FROM stock WHERE store_id=%s AND sku = ANY(%s)",
            (store_id, sku_list)).fetchall()
    return [{"sku": r[0], "available": r[1], "reserved": r[2]} for r in rows]


@app.post("/v1/reserve")
def reserve(req: ReserveRequest):
    ensure_schema()
    if len({i.sku for i in req.items}) != len(req.items):
        raise HTTPException(422, "duplicate sku in items")
    items = sorted(req.items, key=lambda i: i.sku)  # fixed lock order avoids deadlocks
    expires = datetime.now(timezone.utc) + timedelta(seconds=req.ttl_seconds)
    # Leaving the `with` block by exception rolls the whole transaction back,
    # so a 409 on item N undoes the reservations already made for items 1..N-1.
    with _conn() as c:
        existing = c.execute(
            "SELECT sku, qty FROM reservations WHERE order_ref=%s AND status='HELD'",
            (req.order_ref,)).fetchall()
        if existing:  # same order_ref again = retry, not a second reservation
            return {"orderRef": req.order_ref, "status": "ALREADY_RESERVED",
                    "items": [{"sku": s, "qty": q} for s, q in existing]}
        for it in items:
            cur = c.execute(
                "UPDATE stock SET available = available - %s, reserved = reserved + %s "
                "WHERE store_id=%s AND sku=%s AND available >= %s",
                (it.qty, it.qty, req.store_id, it.sku, it.qty))
            if cur.rowcount == 0:
                raise HTTPException(409, {"error": "insufficient_stock", "sku": it.sku})
            c.execute(
                "INSERT INTO reservations (order_ref, store_id, sku, qty, status, expires_at) "
                "VALUES (%s,%s,%s,%s,'HELD',%s)",
                (req.order_ref, req.store_id, it.sku, it.qty, expires))
    return {"orderRef": req.order_ref, "status": "RESERVED",
            "expiresAt": expires.isoformat(),
            "items": [{"sku": i.sku, "qty": i.qty} for i in items]}


@app.post("/v1/release")
def release(req: ReleaseRequest):
    ensure_schema()
    with _conn() as c:
        rows = c.execute(
            "UPDATE reservations SET status='RELEASED' "
            "WHERE order_ref=%s AND status='HELD' RETURNING store_id, sku, qty",
            (req.order_ref,)).fetchall()
        for store, sku, qty in rows:
            c.execute(
                "UPDATE stock SET available = available + %s, reserved = reserved - %s "
                "WHERE store_id=%s AND sku=%s", (qty, qty, store, sku))
    return {"orderRef": req.order_ref, "released": len(rows)}
