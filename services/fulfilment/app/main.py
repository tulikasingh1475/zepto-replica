"""Fulfilment: order stages and rider assignment after payment.
Zepto's picking and dispatch internals are not public, so all of this is Ours."""
import logging
import os
from typing import Literal

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel

log = logging.getLogger("fulfilment")
app = FastAPI(title="fulfilment-service")

DDL = """
CREATE TABLE IF NOT EXISTS riders (
    rider_id text PRIMARY KEY, name text NOT NULL, store_id text NOT NULL,
    status text NOT NULL DEFAULT 'IDLE');
CREATE TABLE IF NOT EXISTS fulfilment (
    order_id text PRIMARY KEY, user_id text NOT NULL, store_id text NOT NULL,
    status text NOT NULL, rider_id text, items jsonb NOT NULL, amount int NOT NULL,
    drop_lat double precision, drop_lng double precision,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
"""
RIDERS = [("R1", "Aman", "S-CP"), ("R2", "Bhavna", "S-CP"), ("R3", "Chirag", "S-KB"), ("R4", "Deepa", "S-KB")]
TRANS = {"accept": ("PLACED", "ACCEPTED"), "pack": ("ACCEPTED", "PACKED"),
         "pickup": ("RIDER_ASSIGNED", "PICKED_UP"), "deliver": ("PICKED_UP", "DELIVERED")}
SELECT = ("SELECT f.order_id, f.user_id, f.store_id, f.status, f.rider_id, r.name, f.items, f.amount, "
          "f.drop_lat, f.drop_lng, f.created_at FROM fulfilment f LEFT JOIN riders r ON r.rider_id=f.rider_id ")
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
            for r in RIDERS:
                c.execute("INSERT INTO riders (rider_id, name, store_id) VALUES (%s,%s,%s) "
                          "ON CONFLICT (rider_id) DO NOTHING", r)
        _ready = True


def _o(r):
    return {"orderId": r[0], "userId": r[1], "storeId": r[2], "status": r[3], "riderId": r[4],
            "riderName": r[5], "items": r[6], "amount": r[7], "dropLat": r[8], "dropLng": r[9],
            "createdAt": r[10].isoformat()}


def commit_stock(order_id: str):
    try:
        httpx.post(f"{os.getenv('INVENTORY_URL', 'http://localhost:8003')}/v1/commit",
                   json={"order_ref": order_id}, timeout=3)
    except httpx.HTTPError:
        log.warning("could not commit stock for %s", order_id)


def assign(c, store_id: str):
    """Give the oldest PACKED order a free rider at the same store. Rider choice: first idle (Ours)."""
    while True:
        o = c.execute("SELECT order_id FROM fulfilment WHERE store_id=%s AND status='PACKED' "
                      "ORDER BY created_at, order_id LIMIT 1 FOR UPDATE SKIP LOCKED", (store_id,)).fetchone()
        r = c.execute("SELECT rider_id FROM riders WHERE store_id=%s AND status='IDLE' "
                      "ORDER BY rider_id LIMIT 1 FOR UPDATE SKIP LOCKED", (store_id,)).fetchone()
        if not o or not r:
            return
        c.execute("UPDATE riders SET status='BUSY' WHERE rider_id=%s", (r[0],))
        c.execute("UPDATE fulfilment SET status='RIDER_ASSIGNED', rider_id=%s, updated_at=now() "
                  "WHERE order_id=%s", (r[0], o[0]))


class OrderIn(BaseModel):
    order_id: str
    user_id: str
    store_id: str
    items: list[dict]
    amount: int
    lat: float | None = None
    lng: float | None = None


class Advance(BaseModel):
    action: Literal["accept", "pack", "pickup", "deliver"]


@app.post("/v1/orders")
def create(req: OrderIn):
    ensure_schema()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO fulfilment (order_id, user_id, store_id, status, items, amount, drop_lat, drop_lng) "
            "VALUES (%s,%s,%s,'PLACED',%s,%s,%s,%s) ON CONFLICT (order_id) DO NOTHING",
            (req.order_id, req.user_id, req.store_id, Jsonb(req.items), req.amount, req.lat, req.lng))
    return {"orderId": req.order_id, "created": cur.rowcount == 1}


@app.get("/v1/orders")
def list_orders(store_id: str | None = None, limit: int = 30):
    ensure_schema()
    q, args = SELECT, []
    if store_id:
        q += "WHERE f.store_id=%s "
        args.append(store_id)
    with _conn() as c:
        rows = c.execute(q + "ORDER BY f.created_at DESC LIMIT %s", (*args, limit)).fetchall()
    return [_o(r) for r in rows]


@app.get("/v1/orders/{order_id}")
def get_order(order_id: str):
    ensure_schema()
    with _conn() as c:
        r = c.execute(SELECT + "WHERE f.order_id=%s", (order_id,)).fetchone()
    if not r:
        raise HTTPException(404, "order not found")
    return _o(r)


@app.post("/v1/orders/{order_id}/advance")
def advance(order_id: str, req: Advance):
    ensure_schema()
    frm, to = TRANS[req.action]
    with _conn() as c:
        row = c.execute("UPDATE fulfilment SET status=%s, updated_at=now() WHERE order_id=%s AND status=%s "
                        "RETURNING store_id, rider_id", (to, order_id, frm)).fetchone()
        if not row:
            raise HTTPException(409, f"order is not in state {frm}")
        store, rider = row
        if req.action == "deliver" and rider:
            c.execute("UPDATE riders SET status='IDLE' WHERE rider_id=%s", (rider,))
        if req.action in ("pack", "deliver"):
            assign(c, store)
    if req.action == "pack":
        commit_stock(order_id)  # packed = sold: the hold leaves `reserved`
    return get_order(order_id)


@app.get("/v1/riders")
def riders(store_id: str | None = None):
    ensure_schema()
    with _conn() as c:
        rows = c.execute("SELECT rider_id, name, store_id, status FROM riders "
                         + ("WHERE store_id=%s " if store_id else "") + "ORDER BY rider_id",
                         (store_id,) if store_id else ()).fetchall()
    return [{"riderId": r[0], "name": r[1], "storeId": r[2], "status": r[3]} for r in rows]


@app.get("/v1/riders/{rider_id}/task")
def task(rider_id: str):
    ensure_schema()
    with _conn() as c:
        r = c.execute(SELECT + "WHERE f.rider_id=%s AND f.status IN ('RIDER_ASSIGNED','PICKED_UP') LIMIT 1",
                      (rider_id,)).fetchone()
    return _o(r) if r else None
