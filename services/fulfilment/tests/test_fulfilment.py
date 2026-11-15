import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import _conn, app, ensure_schema

c = TestClient(app)


def clean():
    with _conn() as db:
        db.execute("DELETE FROM fulfilment WHERE order_id LIKE 'T-%'")
        db.execute("UPDATE riders SET status='IDLE'")


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    ensure_schema()
    committed = []
    monkeypatch.setattr(m, "commit_stock", committed.append)
    clean()
    yield committed
    clean()


def new(oid):
    r = c.post("/v1/orders", json={"order_id": oid, "user_id": "u", "store_id": "S-CP",
                                   "items": [{"sku": "A", "qty": 1}], "amount": 10, "lat": 28.615, "lng": 77.23})
    assert r.status_code == 200


def adv(oid, a):
    return c.post(f"/v1/orders/{oid}/advance", json={"action": a})


def status(oid):
    return c.get(f"/v1/orders/{oid}").json()["status"]


def test_full_flow_and_stock_commit(setup):
    new("T-1")
    assert adv("T-1", "accept").json()["status"] == "ACCEPTED"
    s = adv("T-1", "pack").json()
    assert s["status"] == "RIDER_ASSIGNED" and s["riderId"] and setup == ["T-1"]
    assert adv("T-1", "pickup").json()["status"] == "PICKED_UP"
    assert adv("T-1", "deliver").json()["status"] == "DELIVERED"


def test_illegal_transition_is_409():
    new("T-2")
    assert adv("T-2", "pack").status_code == 409


def test_waits_for_rider_then_is_assigned_after_delivery():
    for i in (3, 4, 5):
        new(f"T-{i}")
        adv(f"T-{i}", "accept")
        adv(f"T-{i}", "pack")
    assert status("T-3") == "RIDER_ASSIGNED" and status("T-4") == "RIDER_ASSIGNED"
    assert status("T-5") == "PACKED"  # S-CP has only 2 riders
    adv("T-3", "pickup")
    adv("T-3", "deliver")
    assert status("T-5") == "RIDER_ASSIGNED"
