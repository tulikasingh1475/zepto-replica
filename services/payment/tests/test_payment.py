import httpx
from fastapi.testclient import TestClient

import app.main as m
from app.main import app

c = TestClient(app)


def test_event_is_delivered_n_times(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return httpx.Response(200, json={"state": "ORDER_CONFIRMED"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(m.httpx, "post", fake_post)
    r = c.post("/v1/pay", json={"order_id": "abc", "amount": 100, "outcome": "success", "deliveries": 2})
    assert r.status_code == 200 and len(calls) == 2
    assert calls[0][0].endswith("/v1/draft-orders/abc/payment") and calls[0][1] == {"status": "SUCCESS"}


def test_failure_outcome_maps_to_failure(monkeypatch):
    seen = []

    def fake_post(url, json=None, timeout=None):
        seen.append(json)
        return httpx.Response(200, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(m.httpx, "post", fake_post)
    c.post("/v1/pay", json={"order_id": "abc", "amount": 1, "outcome": "failure"})
    assert seen == [{"status": "FAILURE"}]
