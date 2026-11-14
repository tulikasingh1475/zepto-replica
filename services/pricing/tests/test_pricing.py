from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)


def q(subtotal, level="NORMAL"):
    return c.post("/v1/quote", json={"subtotal": subtotal, "demand_level": level}).json()


def test_fee_below_threshold():
    r = q(100)
    assert r["deliveryFee"] == 30 and r["total"] == 130


def test_free_at_threshold():
    assert q(199)["deliveryFee"] == 0


def test_busy_has_higher_threshold():
    assert q(250, "BUSY")["deliveryFee"] == 30
    assert q(250)["deliveryFee"] == 0


def test_unknown_level_rejected():
    assert c.post("/v1/quote", json={"subtotal": 10, "demand_level": "NOPE"}).status_code == 422
