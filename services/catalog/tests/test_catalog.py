import pytest
from fastapi.testclient import TestClient
from app.main import app, products

c = TestClient(app)
DOCS = [
    {"sku": "TEST-1", "name": "Test Milk", "brand": "X", "category": "TestCat", "mrp": 50},
    {"sku": "TEST-2", "name": "Test Curd", "brand": "X", "category": "TestCat", "mrp": 30},
]


@pytest.fixture(autouse=True)
def seed():
    col = products()
    col.delete_many({"sku": {"$regex": "^TEST-"}})
    col.insert_many([dict(d) for d in DOCS])
    yield
    col.delete_many({"sku": {"$regex": "^TEST-"}})


def test_get_and_404():
    assert c.get("/v1/products/TEST-1").json()["name"] == "Test Milk"
    assert c.get("/v1/products/NOPE").status_code == 404


def test_batch_keeps_order_and_skips_unknown():
    r = c.post("/v1/products/batch", json={"skus": ["TEST-2", "NOPE", "TEST-1"]})
    assert [p["sku"] for p in r.json()] == ["TEST-2", "TEST-1"]


def test_list_by_category():
    r = c.get("/v1/products", params={"category": "TestCat"})
    assert {p["sku"] for p in r.json()} == {"TEST-1", "TEST-2"}
