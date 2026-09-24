"""Stripe subscriptions: Checkout, customer portal, and the webhook that activates plans."""

import json
from html import escape
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import signed_in
from app.models import User
from app.services import billing
from app.services.pages import page
from app.services.plans import coupon, get_plan
from app.services.stripe_api import StripeClient, StripeError, verify_signature

router = APIRouter()


def get_stripe(settings: Annotated[Settings, Depends(get_settings)]) -> StripeClient:
    try:
        return StripeClient(settings.stripe_secret_key)
    except StripeError as e:
        raise HTTPException(503, {"code": "config", "message": str(e)}) from e


class CheckoutRequest(BaseModel):
    plan: Literal["pro", "team"]
    seats: int = Field(default=1, ge=1, le=500)
    student: bool = False


@router.post("/v1/billing/checkout")
def checkout(
    req: CheckoutRequest,
    user: Annotated[User, Depends(signed_in)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    stripe: Annotated[StripeClient, Depends(get_stripe)],
) -> dict:
    plan = get_plan(req.plan)
    if not plan.stripe_price:
        raise HTTPException(
            503, {"code": "config", "message": f"No Stripe price configured for {plan.name}"}
        )
    try:
        if not user.stripe_customer_id:
            user.stripe_customer_id = stripe.create_customer(user.email, user.id)
            db.commit()
        base = settings.public_url.rstrip("/")
        url = stripe.create_checkout(
            customer=user.stripe_customer_id,
            price=plan.stripe_price,
            quantity=req.seats if plan.per_seat else 1,
            user_id=user.id,
            plan=plan.id,
            success_url=f"{base}/billing/done?status=success",
            cancel_url=f"{base}/billing/done?status=cancel",
            coupon=coupon("student") if req.student else None,
        )
    except StripeError as e:
        raise HTTPException(502, {"code": "billing_error", "message": str(e)}) from e
    return {"url": url}


@router.post("/v1/billing/portal")
def portal(
    user: Annotated[User, Depends(signed_in)],
    settings: Annotated[Settings, Depends(get_settings)],
    stripe: Annotated[StripeClient, Depends(get_stripe)],
) -> dict:
    if not user.stripe_customer_id:
        raise HTTPException(
            400, {"code": "no_subscription", "message": "You don't have a subscription yet."}
        )
    try:
        return {
            "url": stripe.create_portal(
                user.stripe_customer_id, f"{settings.public_url.rstrip('/')}/billing/done"
            )
        }
    except StripeError as e:
        raise HTTPException(502, {"code": "billing_error", "message": str(e)}) from e


@router.post("/v1/billing/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    stripe_signature: Annotated[str | None, Header()] = None,
) -> dict:
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, {"code": "config", "message": "STRIPE_WEBHOOK_SECRET is not set"})
    payload = await request.body()
    try:
        verify_signature(payload, stripe_signature or "", settings.stripe_webhook_secret)
    except StripeError as e:
        raise HTTPException(400, {"code": "bad_signature", "message": str(e)}) from e
    return {"outcome": billing.handle_event(db, json.loads(payload))}


@router.get("/billing/done", response_class=HTMLResponse, include_in_schema=False)
def billing_done(status: str = "") -> HTMLResponse:
    msg = {
        "success": "Thanks. Your plan is active.",
        "cancel": "No problem — nothing was charged.",
    }.get(status, "You're all set.")
    return HTMLResponse(
        page(
            "Nudgy",
            f"""<h1>{escape(msg)}</h1>
<p><a class="btn" href="nudgy://billing?status={escape(status)}">Back to Nudgy</a></p>""",
        )
    )
