import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app

c = TestClient(app)
STORE = {"id": "S1", "name": "DEL-Test", "city": "Delhi", "isActive": True}
PRODUCTS = {"A": [{"sku": "A1", "name": "a1", "category": "A", "mrp": 10},
                  {"sku": "A2", "name": "a2", "category": "A", "mrp": 20}],
            "B": [{"sku": "B1", "name": "b1", "category": "B", "mrp": 30}]}
STOCK = [{"sku": "A1", "available": 5}, {"sku": "A2", "available": 0}, {"sku": "B1", "available": 3}]


def use(monkeypatch, serviceable=True):
    def handler(req: httpx.Request):
        p = req.url.path
        if p == "/v1/serviceability":
            return httpx.Response(200, json={"serviceable": serviceable,
                                             "storeId": "S1" if serviceable else None, "orderable": True})
        if p == "/v1/stores/S1":
            return httpx.Response(200, json=STORE)
        if p == "/v1/categories":
            return httpx.Response(200, json=["A", "B"])
        if p == "/v1/products":
            return httpx.Response(200, json=PRODUCTS[req.url.params["category"]])
        if p == "/v1/stock":
            return httpx.Response(200, json=STOCK)
        if p == "/v1/products/batch":
            return httpx.Response(200, json=[{"sku": "B1", "category": "B"}])
        return httpx.Response(404)

    monkeypatch.setattr(m, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def page(**extra):
    return c.post("/v1/get_page", json={"page_type": "HOME", "lat": 1, "lng": 2, **extra}).json()


def titles(p):
    return [w["title"] for w in p["widgets"] if w["type"] == "PRODUCT_CAROUSEL"]


def test_default_page_and_out_of_stock_dropped(monkeypatch):
    use(monkeypatch)
    p = page()
    assert [w["type"] for w in p["widgets"]] == ["HEADER", "BANNER", "PRODUCT_CAROUSEL", "PRODUCT_CAROUSEL"]
    assert titles(p) == ["A", "B"]
    assert [i["sku"] for i in p["widgets"][2]["items"]] == ["A1"]  # A2 has zero stock
    assert p["storeDetailsResponse"]["id"] == "S1"


def test_cart_boosts_category(monkeypatch):
    use(monkeypatch)
    assert titles(page(cartInfo={"items": [{"sku": "B1", "qty": 1}]})) == ["B", "A"]


def test_history_boosts_category(monkeypatch):
    use(monkeypatch)
    assert titles(page(history=["B"])) == ["B", "A"]


def test_not_serviceable(monkeypatch):
    use(monkeypatch, serviceable=False)
    p = page()
    assert p["storeDetailsResponse"] is None and p["widgets"][0]["type"] == "NOT_SERVICEABLE"
