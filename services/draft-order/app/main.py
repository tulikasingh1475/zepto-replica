"""Draft-Order service. DynamoDB table, ORDER_PK scheme, states, sparse GSI on POS_PK/POS_SK,
two conditional PutItems instead of a transaction, idempotent Create Order to the OMS: Verified (AWS blog).
Inventory reservation at draft time, the manual sweep endpoint and the event stub: Ours."""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import boto3
import httpx
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")

log = logging.getLogger("draft-order")
app = FastAPI(title="draft-order-service")

TABLE = "Draft_Orders"
GSI = "POS_IDX"
_table = None
EVENTS: list[dict] = []  # stand-in for Kafka until Phase 4


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds")


def table():
    global _table
    if _table is None:
        ddb = boto3.resource(
            "dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8010"),
            region_name=os.getenv("AWS_DEFAULT_REGION", "ap-south-1"),
            config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}))
        try:
            ddb.create_table(
                TableName=TABLE,
                KeySchema=[{"AttributeName": "ORDER_PK", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "ORDER_PK", "AttributeType": "S"},
                                      {"AttributeName": "POS_PK", "AttributeType": "S"},
                                      {"AttributeName": "POS_SK", "AttributeType": "S"}],
                GlobalSecondaryIndexes=[{
                    "IndexName": GSI,
                    "KeySchema": [{"AttributeName": "POS_PK", "KeyType": "HASH"},
                                  {"AttributeName": "POS_SK", "KeyType": "RANGE"}],
                    "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": ["CREATED_ON"]}}],
                BillingMode="PAY_PER_REQUEST")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                raise
        t = ddb.Table(TABLE)
        t.wait_until_exists()
        _table = t
    return _table


# ---- calls to other services (small functions so tests can replace them) ----
def reserve(order_id: str, store_id: str, items: list[dict], ttl: int):
    base = os.getenv("INVENTORY_URL", "http://localhost:8003")
    try:
        r = httpx.post(f"{base}/v1/reserve", timeout=3,
                       json={"order_ref": order_id, "store_id": store_id, "items": items, "ttl_seconds": ttl})
    except httpx.HTTPError:
        raise HTTPException(503, "inventory unavailable")
    if r.status_code == 409:
        raise HTTPException(409, r.json().get("detail", "insufficient_stock"))
    if r.status_code >= 400:
        raise HTTPException(502, "inventory error")


def release(order_id: str):
    base = os.getenv("INVENTORY_URL", "http://localhost:8003")
    try:
        httpx.post(f"{base}/v1/release", json={"order_ref": order_id}, timeout=3)
    except httpx.HTTPError:
        log.warning("could not release stock for %s", order_id)


def post_order(payload: dict):
    base = os.getenv("ORDER_URL", "http://localhost:8008")
    httpx.post(f"{base}/v1/orders", json=payload, timeout=3).raise_for_status()


def publish(event: dict):
    EVENTS.append(event)
    log.info("event %s", event)


def notify_fulfilment(payload: dict):
    """Hand a confirmed order to the dark store. Ours. If fulfilment is down the order is not retried."""
    base = os.getenv("FULFILMENT_URL", "http://localhost:8011")
    try:
        httpx.post(f"{base}/v1/orders", json=payload, timeout=3)
    except httpx.HTTPError:
        log.warning("fulfilment unavailable for %s", payload.get("order_id"))


# ---- state helpers ----
def load(order_id: str) -> dict:
    item = table().get_item(Key={"ORDER_PK": f"ORDER_ID#{order_id}"}).get("Item")
    if not item:
        raise HTTPException(404, "draft order not found")
    return item


def set_state(order_id: str, new: str, expected: list[str], clear_pos: bool = False) -> bool:
    vals = {":n": new, ":u": iso(now())}
    for i, e in enumerate(expected):
        vals[f":e{i}"] = e
    cond = "#s IN (" + ",".join(f":e{i}" for i in range(len(expected))) + ")"
    upd = "SET #s = :n, UPDATED_ON = :u" + (" REMOVE POS_PK, POS_SK" if clear_pos else "")
    try:
        table().update_item(Key={"ORDER_PK": f"ORDER_ID#{order_id}"}, UpdateExpression=upd,
                            ConditionExpression=cond, ExpressionAttributeNames={"#s": "STATE"},
                            ExpressionAttributeValues=vals)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def terminate(order_id: str):
    release(order_id)
    set_state(order_id, "ORDER_TERMINATED", ["PAYMENT_UNSUCCESSFUL", "ORDER_RECEIVED"], clear_pos=True)


def confirm(order_id: str) -> dict:
    item = load(order_id)
    if item["STATE"] != "PAYMENT_SUCCESSFUL":
        return {"orderId": order_id, "state": item["STATE"]}
    d = json.loads(item["DATA"])
    try:
        post_order({"order_id": order_id, "user_id": d["user_id"], "store_id": d["store_id"],
                    "items": d["items"], "amount": d["amount"]})
    except httpx.HTTPError:
        return {"orderId": order_id, "state": "PAYMENT_SUCCESSFUL",
                "note": "order service unavailable; sweep will retry"}
    set_state(order_id, "ORDER_CONFIRMED", ["PAYMENT_SUCCESSFUL"])
    notify_fulfilment({"order_id": order_id, "user_id": d["user_id"], "store_id": d["store_id"],
                       "items": d["items"], "amount": d["amount"], "lat": d.get("lat"), "lng": d.get("lng")})
    publish({"type": "order.confirmed", "orderId": order_id})
    return {"orderId": order_id, "state": "ORDER_CONFIRMED"}


# ---- API ----
class Item(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class DraftReq(BaseModel):
    user_id: str
    store_id: str
    items: list[Item] = Field(min_length=1)
    amount: int = Field(ge=0)
    ttl_seconds: int = Field(300, gt=0)
    lat: float | None = None
    lng: float | None = None


class PaymentEvent(BaseModel):
    status: Literal["SUCCESS", "FAILURE"]


@app.post("/v1/draft-orders")
def create(req: DraftReq):
    t = table()  # fail fast if DynamoDB is down, before touching stock
    order_id = uuid.uuid4().hex
    code = order_id[:8].upper()
    created = now()
    expire = created + timedelta(seconds=req.ttl_seconds)
    items = [i.model_dump() for i in req.items]
    reserve(order_id, req.store_id, items, req.ttl_seconds)
    data = json.dumps({"user_id": req.user_id, "store_id": req.store_id, "items": items,
                       "amount": req.amount, "lat": req.lat, "lng": req.lng})
    try:
        t.put_item(Item={"ORDER_PK": f"ORDER_ID#{order_id}", "STATE": "ORDER_RECEIVED",
                         "EXPIRE_AT": int(expire.timestamp()), "DATA": data,
                         "POS_PK": "PENDING", "POS_SK": iso(expire),
                         "CREATED_ON": iso(created), "UPDATED_ON": iso(created)},
                   ConditionExpression="attribute_not_exists(ORDER_PK)")
        t.put_item(Item={"ORDER_PK": f"ORDER_CODE#{code}", "DATA": json.dumps({"order_id": order_id}),
                         "CREATED_ON": iso(created), "UPDATED_ON": iso(created)},
                   ConditionExpression="attribute_not_exists(ORDER_PK)")
    except ClientError:
        release(order_id)
        t.delete_item(Key={"ORDER_PK": f"ORDER_ID#{order_id}"})
        raise HTTPException(500, "could not create draft order")
    return {"orderId": order_id, "orderCode": code, "state": "ORDER_RECEIVED", "expiresAt": iso(expire)}


@app.get("/v1/draft-orders/{order_id}")
def get_draft(order_id: str):
    item = load(order_id)
    return {"orderId": order_id, "state": item["STATE"], "data": json.loads(item["DATA"])}


@app.post("/v1/draft-orders/{order_id}/payment")
def payment(order_id: str, ev: PaymentEvent):
    item = load(order_id)
    if item["STATE"] in ("ORDER_CONFIRMED", "ORDER_TERMINATED"):
        return {"orderId": order_id, "state": item["STATE"], "duplicate": True}
    if ev.status == "FAILURE":
        if set_state(order_id, "PAYMENT_UNSUCCESSFUL", ["ORDER_RECEIVED"], clear_pos=True):
            terminate(order_id)
        return {"orderId": order_id, "state": load(order_id)["STATE"]}
    set_state(order_id, "PAYMENT_SUCCESSFUL", ["ORDER_RECEIVED"], clear_pos=True)
    return confirm(order_id)


@app.post("/v1/sweep")
def sweep():
    """Manual trigger for the 5-minute sweep (a scheduler can call it). Ours.
    1) expire pending drafts via the sparse GSI; 2) retry paid-but-unconfirmed orders (table scan: local only)."""
    t = table()
    due = t.query(IndexName=GSI, KeyConditionExpression=Key("POS_PK").eq("PENDING") & Key("POS_SK").lte(iso(now())))["Items"]
    terminated = 0
    for it in due:
        oid = it["ORDER_PK"].split("#", 1)[1]
        if set_state(oid, "ORDER_TERMINATED", ["ORDER_RECEIVED"], clear_pos=True):
            release(oid)
            terminated += 1
    paid = t.scan(FilterExpression=Attr("STATE").eq("PAYMENT_SUCCESSFUL"))["Items"]
    confirmed = sum(1 for it in paid
                    if confirm(it["ORDER_PK"].split("#", 1)[1])["state"] == "ORDER_CONFIRMED")
    return {"terminated": terminated, "retried": len(paid), "confirmed": confirmed}
