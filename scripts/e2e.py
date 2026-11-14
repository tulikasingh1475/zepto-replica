"""End-to-end smoke test: app open -> search -> cart -> draft order -> payment -> order.
Needs every service running (scripts/dev.sh start). Each run permanently holds a little stock."""
import sys
import uuid

import httpx

LAT, LNG = 28.615, 77.23
user = "e2e-" + uuid.uuid4().hex[:6]


def u(port, path):
    return f"http://localhost:{port}{path}"


def ok(r):
    r.raise_for_status()
    return r.json()


page = ok(httpx.post(u(8000, "/v1/get_page"), json={"page_type": "HOME", "lat": LAT, "lng": LNG}))
store = page["storeDetailsResponse"]["id"]
print("1. home page  ->", store, [w["type"] for w in page["widgets"]])

res = ok(httpx.get(u(8004, "/v1/search"), params={"q": "milk", "lat": LAT, "lng": LNG}))["results"]
if not res:
    sys.exit("search returned nothing")
item = res[0]
print("2. search     ->", item["sku"], item["name"], "available", item["available"])

qty = min(2, item["available"])
ok(httpx.put(u(8005, f"/v1/cart/{user}/items"), json={"store_id": store, "sku": item["sku"], "qty": qty}))
cart = ok(httpx.get(u(8005, f"/v1/cart/{user}"), params={"store_id": store}))
print("3. cart       ->", cart["items"], "subtotal", cart["subtotal"], "fee", cart["deliveryFee"], "total", cart["total"])

d = ok(httpx.post(u(8007, "/v1/draft-orders"), json={
    "user_id": user, "store_id": store, "amount": cart["total"],
    "items": [{"sku": i["sku"], "qty": i["qty"]} for i in cart["items"]]}))
print("4. draft      ->", d["orderId"], d["state"])

pay = ok(httpx.post(u(8009, "/v1/pay"), json={"order_id": d["orderId"], "amount": cart["total"],
                                              "outcome": "success", "deliveries": 2}))
print("5. payment    ->", pay["draftOrder"])

order = ok(httpx.get(u(8008, f"/v1/orders/{d['orderId']}")))
print("6. order      ->", order["status"], order["amount"])
assert order["status"] == "CONFIRMED" and order["amount"] == cart["total"]

stock = ok(httpx.get(u(8003, "/v1/stock"), params={"store_id": store, "skus": item["sku"]}))
print("7. stock now  ->", stock)
ok(httpx.delete(u(8005, f"/v1/cart/{user}"), params={"store_id": store}))
print("PASS: app open to order placed")
