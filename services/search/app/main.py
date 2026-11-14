"""Search service. Orchestration: Ours."""
import os

import httpx
from fastapi import FastAPI, HTTPException

from app.orchestrator import search

app = FastAPI(title="search-service")


@app.get("/v1/search")
async def do_search(q: str, lat: float, lng: float, size: int = 20):
    store_url = os.getenv("STORE_URL", "http://localhost:8001")
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            svc = (await c.get(f"{store_url}/v1/serviceability",
                               params={"lat": lat, "lng": lng})).json()
            if not svc["serviceable"]:
                return {"serviceable": False, "results": []}
            store = (await c.get(f"{store_url}/v1/stores/{svc['storeId']}")).json()
        results = await search(q, store["city"], svc["storeId"], size)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"dependency failed: {e.__class__.__name__}")
    return {"serviceable": True, "storeId": svc["storeId"], "results": results}
