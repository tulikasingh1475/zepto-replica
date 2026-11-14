import asyncio

import httpx
import pytest

from app.indexer import build_docs, load_index
from app.orchestrator import search
from app.retrieval import client, retrieve

TEST_INDEX = "products_test"


@pytest.fixture(scope="module")
def index():
    products = [
        {"sku": "T-1", "name": "Pure Milk", "brand": "A", "category": "Dairy"},
        {"sku": "T-2", "name": "Curd Cup", "brand": "A", "category": "Dairy"},
        {"sku": "T-3", "name": "Milk Bread", "brand": "B", "category": "Bakery"},
    ]
    stock = [("H1", "T-1", 5), ("H1", "T-2", 5), ("H1", "T-3", 0), ("H2", "T-1", 5)]
    load_index(build_docs(products, stock), TEST_INDEX)
    yield
    client().indices.delete(index=TEST_INDEX, ignore=[404])


def skus(q, hubs, city="Delhi"):
    return [h["sku"] for h in retrieve(q, city, hubs, index=TEST_INDEX)]


def test_matches_by_name(index):
    assert skus("milk", ["H1"]) == ["T-1"]  # T-3 matches text but H1 has it out of stock


def test_inactive_hub_excluded(index):
    assert "T-2" not in skus("curd", ["H2"])


def test_typo_tolerance(index):
    assert "T-1" in skus("mlik", ["H1"])


def test_other_city_empty(index):
    assert skus("milk", ["H1"], city="Mumbai") == []


def test_orchestrator_drops_out_of_stock():
    def fake_retrieve(q, city, hubs, size):
        return [{"sku": "A", "score": 2.0}, {"sku": "B", "score": 1.0}]

    def handler(req: httpx.Request):
        if req.url.path == "/v1/products/batch":
            return httpx.Response(200, json=[{"sku": "A", "name": "a"}, {"sku": "B", "name": "b"}])
        return httpx.Response(200, json=[{"sku": "A", "available": 0, "reserved": 0},
                                         {"sku": "B", "available": 3, "reserved": 0}])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await search("x", "Delhi", "S", client=c, retrieve_fn=fake_retrieve)

    out = asyncio.run(run())
    assert [p["sku"] for p in out] == ["B"] and out[0]["available"] == 3
