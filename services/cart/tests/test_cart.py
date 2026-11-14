import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import _conn, app, ensure_schema

c = TestClient(app)
USER, STORE = "T-USER", "S"
STOCK = {"SKU-X": 5}


def handler(req: httpx.Request):
    p = req.url.path
    if p == "/v1/stock":
        sku = req.url.params["skus"]
        return httpx.Response(200, json=[{"sku": sku, "available": STOCK.get(sku, 0), "reserved": 0}])
    if p == "/v1/products/batch":
        return httpx.Response(200, json=[{"sku": "SKU-X", "name": "X", "mrp": 100}])
    if p == "/v1/quote":
        sub = json.loads(req.content)["subtotal"]
        return httpx.Response(200, json={"subtotal": sub, "deliveryFee": 30,
                                         "freeDeliveryAbove": 199, "total": sub + 30})
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    ensure_schema()
    monkeypatch.setattr(m, "http", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    with _conn() as db:
        db.execute("DELETE FROM cart_items WHERE user_id=%s", (USER,))
    yield
    with _conn() as db:
        db.execute("DELETE FROM cart_items WHERE user_id=%s", (USER,))


def put(qty, sku="SKU-X"):
    return c.put(f"/v1/cart/{USER}/items", json={"store_id": STORE, "sku": sku, "qty": qty})


def get():
    return c.get(f"/v1/cart/{USER}", params={"store_id": STORE}).json()


def test_add_and_price():
    assert put(2).status_code == 200
    cart = get()
    assert cart["subtotal"] == 200 and cart["deliveryFee"] == 30 and cart["total"] == 230
    assert cart["items"][0]["lineTotal"] == 200


def test_over_stock_is_409_and_cart_unchanged():
    assert put(6).status_code == 409
    assert get()["items"] == []


def test_qty_zero_removes():
    put(1)
    put(0)
    assert get()["items"] == []


def test_empty_cart_is_zero():
    assert get()["total"] == 0
