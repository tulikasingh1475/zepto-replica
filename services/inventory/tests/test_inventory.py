from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import Item, ReserveRequest, _conn, app, ensure_schema, reserve

c = TestClient(app)
STORE = "T-STORE"


@pytest.fixture(autouse=True)
def clean():
    ensure_schema()
    with _conn() as db:
        db.execute("DELETE FROM reservations WHERE store_id=%s", (STORE,))
        db.execute("DELETE FROM stock WHERE store_id=%s", (STORE,))
        db.execute("INSERT INTO stock (store_id, sku, available) VALUES (%s,'TEST-A',10),(%s,'TEST-B',2)",
                   (STORE, STORE))
    yield


def stock(sku):
    r = c.get("/v1/stock", params={"store_id": STORE, "skus": sku}).json()[0]
    return r["available"], r["reserved"]


def body(ref, items):
    return {"order_ref": ref, "store_id": STORE, "items": items}


def test_reserve_moves_available_to_reserved():
    r = c.post("/v1/reserve", json=body("T-1", [{"sku": "TEST-A", "qty": 3}]))
    assert r.status_code == 200 and r.json()["status"] == "RESERVED"
    assert stock("TEST-A") == (7, 3)


def test_shortage_returns_409_and_is_atomic():
    r = c.post("/v1/reserve", json=body("T-2", [{"sku": "TEST-A", "qty": 1}, {"sku": "TEST-B", "qty": 5}]))
    assert r.status_code == 409
    assert stock("TEST-A") == (10, 0)  # first item rolled back
    assert stock("TEST-B") == (2, 0)


def test_same_order_ref_is_idempotent():
    c.post("/v1/reserve", json=body("T-3", [{"sku": "TEST-A", "qty": 2}]))
    r = c.post("/v1/reserve", json=body("T-3", [{"sku": "TEST-A", "qty": 2}]))
    assert r.json()["status"] == "ALREADY_RESERVED"
    assert stock("TEST-A") == (8, 2)


def test_release_restores_stock_and_is_repeatable():
    c.post("/v1/reserve", json=body("T-4", [{"sku": "TEST-A", "qty": 4}]))
    assert c.post("/v1/release", json={"order_ref": "T-4"}).json()["released"] == 1
    assert stock("TEST-A") == (10, 0)
    assert c.post("/v1/release", json={"order_ref": "T-4"}).json()["released"] == 0


def test_no_oversell_under_concurrency():
    def attempt(i):
        try:
            reserve(ReserveRequest(order_ref=f"T-CC-{i}", store_id=STORE,
                                   items=[Item(sku="TEST-A", qty=1)]))
            return True
        except HTTPException as e:
            assert e.status_code == 409
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(attempt, range(25)))
    assert sum(results) == 10          # exactly the stock on hand
    assert stock("TEST-A") == (0, 10)
