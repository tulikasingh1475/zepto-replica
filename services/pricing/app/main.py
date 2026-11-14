"""Pricing service. Fee behaviour: Observed (reported thresholds, may change).
Rules-in-a-table design and the fee amount: Ours. Seed rows are seed data, not guaranteed."""
import os

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="pricing-service")

DDL = """
CREATE TABLE IF NOT EXISTS fee_rules (
    demand_level text PRIMARY KEY,
    free_above   int NOT NULL,
    fee          int NOT NULL
);
"""
SEED = [("NORMAL", 199, 30), ("BUSY", 299, 30)]
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
            for row in SEED:
                c.execute("INSERT INTO fee_rules VALUES (%s,%s,%s) ON CONFLICT (demand_level) DO NOTHING", row)
        _ready = True


class QuoteReq(BaseModel):
    subtotal: int = Field(ge=0)
    demand_level: str = "NORMAL"


@app.post("/v1/quote")
def quote(req: QuoteReq):
    ensure_schema()
    with _conn() as c:
        row = c.execute("SELECT free_above, fee FROM fee_rules WHERE demand_level=%s",
                        (req.demand_level,)).fetchone()
    if not row:
        raise HTTPException(422, f"unknown demand_level {req.demand_level}")
    free_above, fee = row
    delivery = 0 if req.subtotal == 0 or req.subtotal >= free_above else fee
    return {"subtotal": req.subtotal, "deliveryFee": delivery,
            "freeDeliveryAbove": free_above, "total": req.subtotal + delivery}
