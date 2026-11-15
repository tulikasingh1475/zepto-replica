import time

import pytest
from fastapi.testclient import TestClient

from app.main import _conn, app, ensure_schema

c = TestClient(app)
STORE = "T-STORE2"


@pytest.fixture(autouse=True)
def clean():
    ensure_schema()
    with _conn() as db:
        db.execute("DELETE FROM reservations WHERE store_id=%s", (STORE,))
        db.execute("DELETE FROM stock WHERE store_id=%s", (STORE,))
        db.execute("INSERT INTO stock (store_id, sku, available) VALUES (%s,'TEST-A',10)", (STORE,))


def stock():
    r = c.get("/v1/stock", params={"store_id": STORE, "skus": "TEST-A"}).json()[0]
    return r["available"], r["reserved"]


def reserve(ref, ttl=600):
    return c.post("/v1/reserve", json={"order_ref": ref, "store_id": STORE, "ttl_seconds": ttl,
                                       "items": [{"sku": "TEST-A", "qty": 3}]})


def test_commit_turns_hold_into_sale():
    reserve("T-C1")
    assert c.post("/v1/commit", json={"order_ref": "T-C1"}).json()["committed"] == 1
    assert stock() == (7, 0)
    assert c.post("/v1/commit", json={"order_ref": "T-C1"}).json()["committed"] == 0


def test_expire_returns_stock():
    reserve("T-C2", ttl=1)
    time.sleep(1.3)
    assert c.post("/v1/expire").json()["expired"] >= 1
    assert stock() == (10, 0)
    assert c.get("/v1/reservations", params={"store_id": STORE}).json()[0]["status"] == "EXPIRED"
