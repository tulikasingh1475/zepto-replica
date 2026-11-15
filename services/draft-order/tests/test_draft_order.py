import time

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as m
from app.main import app

c = TestClient(app)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    calls = {"reserve": [], "release": [], "orders": []}
    monkeypatch.setattr(m, "reserve", lambda oid, store, items, ttl: calls["reserve"].append(oid))
    monkeypatch.setattr(m, "release", lambda oid: calls["release"].append(oid))
    monkeypatch.setattr(m, "notify_fulfilment", lambda payload: None)
    monkeypatch.setattr(m, "post_order", lambda payload: calls["orders"].append(payload["order_id"]))
    return calls


def draft(ttl=300):
    r = c.post("/v1/draft-orders", json={"user_id": "u1", "store_id": "S", "amount": 100,
                                         "items": [{"sku": "SKU-1", "qty": 1}], "ttl_seconds": ttl})
    assert r.status_code == 200, r.text
    return r.json()["orderId"]


def pay(oid, status):
    return c.post(f"/v1/draft-orders/{oid}/payment", json={"status": status}).json()


def state(oid):
    return c.get(f"/v1/draft-orders/{oid}").json()["state"]


def test_create_reserves_stock_and_starts_received(fakes):
    oid = draft()
    assert state(oid) == "ORDER_RECEIVED" and fakes["reserve"] == [oid]


def test_success_confirms_once_even_if_event_repeats(fakes):
    oid = draft()
    assert pay(oid, "SUCCESS")["state"] == "ORDER_CONFIRMED"
    assert pay(oid, "SUCCESS")["duplicate"] is True
    assert fakes["orders"] == [oid]


def test_failure_terminates_and_releases_stock(fakes):
    oid = draft()
    pay(oid, "FAILURE")
    assert state(oid) == "ORDER_TERMINATED" and fakes["release"] == [oid] and fakes["orders"] == []


def test_order_service_down_then_sweep_confirms(fakes, monkeypatch):
    def boom(payload):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(m, "post_order", boom)
    oid = draft()
    pay(oid, "SUCCESS")
    assert state(oid) == "PAYMENT_SUCCESSFUL"
    monkeypatch.setattr(m, "post_order", lambda payload: fakes["orders"].append(payload["order_id"]))
    c.post("/v1/sweep")
    assert state(oid) == "ORDER_CONFIRMED" and fakes["orders"] == [oid]


def test_expired_draft_is_terminated_by_sweep(fakes):
    oid = draft(ttl=1)
    time.sleep(1.5)
    assert c.post("/v1/sweep").json()["terminated"] >= 1
    assert state(oid) == "ORDER_TERMINATED" and oid in fakes["release"]


def test_stock_conflict_returns_409(monkeypatch):
    def conflict(*a):
        raise HTTPException(409, "insufficient_stock")

    monkeypatch.setattr(m, "reserve", conflict)
    r = c.post("/v1/draft-orders", json={"user_id": "u", "store_id": "S", "amount": 1,
                                         "items": [{"sku": "X", "qty": 1}]})
    assert r.status_code == 409
