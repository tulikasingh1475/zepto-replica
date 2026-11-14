"""Page service (BFF). Request/response shape (get_page, page_type, cartInfo, storeDetailsResponse):
Observed (single third-party source, ~Mar 2026). Widget contents and ranker stub: Ours."""
import asyncio
import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="page-service")

CART_BOOST = 2.0
HISTORY_BOOST = 1.0
MAX_CAROUSELS = 5
ITEMS_PER_CAROUSEL = 8


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=2.0)


def _u(name, default):
    return os.getenv(name, default)


class GetPageRequest(BaseModel):
    page_type: str = "HOME"
    lat: float
    lng: float
    cartInfo: dict | None = None  # ours: {"items": [{"sku": "...", "qty": 1}]}
    history: list[str] = Field(default_factory=list)  # ours: categories the user bought before


def rank_categories(categories: list[str], cart_cats: set[str], history: list[str]) -> list[str]:
    """Stub ranker: base 1.0, boost for categories in the cart (in-session) and in history."""
    score = {c: 1.0 + (CART_BOOST if c in cart_cats else 0.0) + (HISTORY_BOOST if c in history else 0.0)
             for c in categories}
    return sorted(categories, key=lambda c: -score[c])  # stable: ties keep catalog order


@app.post("/v1/get_page")
async def get_page(req: GetPageRequest):
    store_url = _u("STORE_URL", "http://localhost:8001")
    catalog_url = _u("CATALOG_URL", "http://localhost:8002")
    inv_url = _u("INVENTORY_URL", "http://localhost:8003")
    try:
        async with make_client() as c:
            svc = (await c.get(f"{store_url}/v1/serviceability",
                               params={"lat": req.lat, "lng": req.lng})).json()
            if not svc["serviceable"]:
                return {"pageType": req.page_type, "storeDetailsResponse": None,
                        "widgets": [{"type": "NOT_SERVICEABLE",
                                     "message": "We are not delivering to this location yet"}]}
            store_id = svc["storeId"]
            store_r, cats_r = await asyncio.gather(c.get(f"{store_url}/v1/stores/{store_id}"),
                                                   c.get(f"{catalog_url}/v1/categories"))
            store, cats = store_r.json(), cats_r.json()
            lists = await asyncio.gather(*[c.get(f"{catalog_url}/v1/products",
                                                 params={"category": cat, "limit": 12}) for cat in cats])
            by_cat = {cat: r.json() for cat, r in zip(cats, lists)}
            all_skus = [p["sku"] for ps in by_cat.values() for p in ps]
            stock_r = await c.get(f"{inv_url}/v1/stock",
                                  params={"store_id": store_id, "skus": ",".join(all_skus)})
            cart_skus = [i["sku"] for i in (req.cartInfo or {}).get("items", []) if "sku" in i]
            cart_cats: set[str] = set()
            if cart_skus:
                rb = await c.post(f"{catalog_url}/v1/products/batch", json={"skus": cart_skus})
                cart_cats = {p["category"] for p in rb.json()}
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise HTTPException(503, f"dependency failed: {e.__class__.__name__}")

    available = {s["sku"]: s["available"] for s in stock_r.json()}
    widgets = [{"type": "HEADER", "storeName": store["name"], "orderable": svc["orderable"]},
               {"type": "BANNER", "title": "Fresh groceries from your nearest store"}]
    for cat in rank_categories(cats, cart_cats, req.history)[:MAX_CAROUSELS]:
        items = [{"sku": p["sku"], "name": p["name"], "mrp": p["mrp"], "image": p.get("image"),
                  "available": available[p["sku"]]}
                 for p in by_cat[cat] if available.get(p["sku"], 0) > 0][:ITEMS_PER_CAROUSEL]
        if items:
            widgets.append({"type": "PRODUCT_CAROUSEL", "title": cat, "items": items})
    return {"pageType": req.page_type, "storeDetailsResponse": store, "widgets": widgets}
