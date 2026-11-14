"""Store service. Response shape: Observed. Nearest-store tie-break: Ours."""
import json
import math
from pathlib import Path

from fastapi import FastAPI, HTTPException
from shapely.geometry import Point, Polygon

app = FastAPI(title="store-service")
_DATA = Path(__file__).parent / "stores.json"


def _load() -> list[dict]:
    return json.loads(_DATA.read_text())


def _polygon(store: dict) -> Polygon:
    # Geofences are stored [lat, lng]; shapely wants (x, y) = (lng, lat).
    return Polygon([(lng, lat) for lat, lng in store["servicableGeofence"]])


def _km(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(a))


@app.get("/v1/stores/{store_id}")
def get_store(store_id: str):
    for s in _load():
        if s["id"] == store_id:
            return s
    raise HTTPException(404, "store not found")


@app.get("/v1/serviceability")
def serviceability(lat: float, lng: float):
    point = Point(lng, lat)
    candidates = [s for s in _load() if s["isActive"] and _polygon(s).covers(point)]
    if not candidates:
        return {"serviceable": False, "storeId": None, "orderable": False}
    best = min(candidates, key=lambda s: _km(lat, lng, s["lat"], s["lng"]))
    return {
        "serviceable": True,
        "storeId": best["id"],
        # isActive = store exists in the network; isOnline/isLive = taking orders now
        "orderable": best["isOnline"] and best["isLive"],
    }
