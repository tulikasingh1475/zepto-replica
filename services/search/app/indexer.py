"""Builds one doc per city+product from Mongo (catalog) and Postgres (stock). Ours."""
import os
import random

import psycopg
from opensearchpy import helpers
from pymongo import MongoClient

from app.retrieval import INDEX, MAPPING, client

CITY = "Delhi"  # both seeded stores are in Delhi


def build_docs(products: list[dict], stock_rows: list[tuple]) -> list[dict]:
    """stock_rows: (store_id, sku, available)."""
    rng = random.Random(7)
    by_sku: dict[str, list[tuple]] = {}
    for store, sku, avail in stock_rows:
        by_sku.setdefault(sku, []).append((store, avail))
    docs = []
    for p in products:
        hubs = [{"hub_id": s, "stock_status": "IN_STOCK" if a > 0 else "OUT_OF_STOCK",
                 "rpi_score": round(rng.random(), 3), "active": a > 0}
                for s, a in by_sku.get(p["sku"], [])]
        docs.append({"_id": f"{CITY}:{p['sku']}", "city": CITY, "sku": p["sku"],
                     "name": p["name"], "brand": p["brand"], "category": p["category"],
                     "hubs": hubs, "active_hubs": [h["hub_id"] for h in hubs if h["active"]]})
    return docs


def load_index(docs: list[dict], index: str, os_client=None):
    c = os_client or client()
    if c.indices.exists(index=index):
        c.indices.delete(index=index)
    c.indices.create(index=index, body=MAPPING)
    helpers.bulk(c, ({"_index": index, **d} for d in docs))
    c.indices.refresh(index=index)  # force visibility now instead of waiting up to 10s


def main():
    g = os.getenv
    mongo = MongoClient(g("MONGO_URL", "mongodb://localhost:27017"), serverSelectionTimeoutMS=3000)
    products = list(mongo[g("MONGO_DB", "zepto_catalog")]["products"]
                    .find({"sku": {"$regex": "^SKU-"}}, {"_id": 0}))
    dsn = (f"host={g('POSTGRES_HOST', 'localhost')} port={g('POSTGRES_PORT', '5433')} "
           f"user={g('POSTGRES_USER', 'zepto')} password={g('POSTGRES_PASSWORD', 'zepto_dev')} "
           f"dbname={g('POSTGRES_DB', 'zepto')}")
    with psycopg.connect(dsn) as c:
        rows = c.execute("SELECT store_id, sku, available FROM stock WHERE sku LIKE 'SKU-%'").fetchall()
    docs = build_docs(products, rows)
    load_index(docs, INDEX)
    print(f"indexed {len(docs)} docs into '{INDEX}'")


if __name__ == "__main__":
    main()
