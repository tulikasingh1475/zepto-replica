"""Catalog service. Store choice (MongoDB): Verified. API shape: Ours."""
import os

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient

app = FastAPI(title="catalog-service")

_client = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"),
                      serverSelectionTimeoutMS=2000)
_indexed = False


def products():
    global _indexed
    col = _client[os.getenv("MONGO_DB", "zepto_catalog")]["products"]
    if not _indexed:
        col.create_index("sku", unique=True)
        col.create_index("category")
        _indexed = True
    return col


class BatchRequest(BaseModel):
    skus: list[str] = Field(min_length=1, max_length=200)


@app.get("/v1/products/{sku}")
def get_product(sku: str):
    doc = products().find_one({"sku": sku}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "product not found")
    return doc


@app.post("/v1/products/batch")
def get_batch(req: BatchRequest):
    docs = {d["sku"]: d for d in products().find({"sku": {"$in": req.skus}}, {"_id": 0})}
    # keep the caller's order (search ranking depends on it); silently skip unknown SKUs
    return [docs[s] for s in req.skus if s in docs]


@app.get("/v1/products")
def list_products(category: str | None = None, limit: int = Query(20, ge=1, le=100)):
    q = {"category": category} if category else {}
    return list(products().find(q, {"_id": 0}).limit(limit))


@app.get("/v1/categories")
def categories():
    return sorted(products().distinct("category"))
