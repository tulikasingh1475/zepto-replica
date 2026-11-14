"""Retrieval -> (catalog + inventory in parallel) -> drop out-of-stock. Ours.
Re-checking stock here is what makes a stale index acceptable (Verified idea)."""
import asyncio
import os

import httpx

from app.retrieval import retrieve


async def search(q: str, city: str, store_id: str, size: int = 20, *,
                 client: httpx.AsyncClient | None = None, retrieve_fn=retrieve) -> list[dict]:
    hits = await asyncio.to_thread(retrieve_fn, q, city, [store_id], size)
    if not hits:
        return []
    skus = [h["sku"] for h in hits]
    scores = {h["sku"]: h["score"] for h in hits}
    catalog_url = os.getenv("CATALOG_URL", "http://localhost:8002")
    inventory_url = os.getenv("INVENTORY_URL", "http://localhost:8003")
    own = client is None
    client = client or httpx.AsyncClient(timeout=2.0)
    try:
        cat_r, inv_r = await asyncio.gather(
            client.post(f"{catalog_url}/v1/products/batch", json={"skus": skus}),
            client.get(f"{inventory_url}/v1/stock",
                       params={"store_id": store_id, "skus": ",".join(skus)}),
        )
        cat_r.raise_for_status()
        inv_r.raise_for_status()
    finally:
        if own:
            await client.aclose()
    available = {s["sku"]: s["available"] for s in inv_r.json()}
    out = []
    for p in cat_r.json():  # catalog keeps the retrieval order
        if available.get(p["sku"], 0) > 0:
            out.append({**p, "available": available[p["sku"]], "score": scores[p["sku"]]})
    return out
