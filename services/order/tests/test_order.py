import pytest
from fastapi.testclient import TestClient

from app.main import _conn, app, ensure_schema

c = TestClient(app)
BODY = {"order_id": "T-ORD-1", "user_id": "u", "store_id": "S", "items": [{"sku": "A", "qty": 1}], "amount": 100}


@pytest.fixture(autouse=True)
def clean():
    ensure_schema()
    with _conn() as db:
        db.execute("DELETE FROM orders WHERE order_id LIKE 'T-%'")
    yield
    with _conn() as db:
        db.execute("DELETE FROM orders WHERE order_id LIKE 'T-%'")


def test_create_is_idempotent():
    assert c.post("/v1/orders", json=BODY).json()["created"] is True
    assert c.post("/v1/orders", json=BODY).json()["created"] is False
    with _conn() as db:
        assert db.execute("SELECT count(*) FROM orders WHERE order_id='T-ORD-1'").fetchone()[0] == 1


def test_get_and_404():
    c.post("/v1/orders", json=BODY)
    assert c.get("/v1/orders/T-ORD-1").json()["amount"] == 100
    assert c.get("/v1/orders/NOPE").status_code == 404
