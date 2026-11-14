from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)


def svc(lat, lng):
    return c.get("/v1/serviceability", params={"lat": lat, "lng": lng}).json()


def test_inside_single_geofence():
    r = svc(28.615, 77.23)
    assert r["serviceable"] and r["storeId"] == "S-CP" and r["orderable"]


def test_overlap_picks_nearest():
    assert svc(28.640, 77.205)["storeId"] == "S-CP"


def test_outside_city():
    r = svc(19.07, 72.87)
    assert not r["serviceable"] and r["storeId"] is None


def test_inactive_store_not_serviceable():
    assert not svc(28.50, 77.10)["serviceable"]


def test_get_store_and_404():
    assert c.get("/v1/stores/S-CP").json()["name"] == "DEL-Connaught Place"
    assert c.get("/v1/stores/NOPE").status_code == 404
