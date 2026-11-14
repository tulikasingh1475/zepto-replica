"""Payment mock. Stands in for the real gateway (Cashfree / UPI in reality): Ours.
It delivers a payment event to draft-order, optionally several times to prove idempotency."""
import os
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="payment-mock")


class PayReq(BaseModel):
    order_id: str
    amount: int
    outcome: Literal["success", "failure"] = "success"
    deliveries: int = Field(1, ge=1, le=5)


@app.post("/v1/pay")
def pay(req: PayReq):
    status = "SUCCESS" if req.outcome == "success" else "FAILURE"
    base = os.getenv("DRAFT_ORDER_URL", "http://localhost:8007")
    result = None
    for _ in range(req.deliveries):
        try:
            r = httpx.post(f"{base}/v1/draft-orders/{req.order_id}/payment",
                           json={"status": status}, timeout=5)
            r.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502, "draft-order did not accept the payment event")
        result = r.json()
    return {"orderId": req.order_id, "paymentStatus": status,
            "deliveries": req.deliveries, "draftOrder": result}
