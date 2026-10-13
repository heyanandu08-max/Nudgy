"""PayPal subscriptions: start a subscription, the return page that confirms it, the link to
manage it, and the webhook that keeps plans in sync."""

import json
import logging
from html import escape
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import signed_in
from app.models import User
from app.services import billing
from app.services.pages import page
from app.services.paypal_api import PayPalClient, PayPalError
from app.services.plans import get_plan

log = logging.getLogger("nudgy.billing")
router = APIRouter()


def get_paypal(settings: Annotated[Settings, Depends(get_settings)]) -> PayPalClient:
    try:
        return PayPalClient(
            settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_env
        )
    except PayPalError as e:
        raise HTTPException(503, {"code": "config", "message": str(e)}) from e


def optional_paypal(settings: Annotated[Settings, Depends(get_settings)]) -> PayPalClient | None:
    try:
        return get_paypal(settings)
    except HTTPException:
        return None


class CheckoutRequest(BaseModel):
    plan: Literal["pro", "team"]
    interval: Literal["month", "year"] = "month"
    seats: int = Field(default=1, ge=1, le=500)


@router.post("/v1/billing/checkout")
def checkout(
    req: CheckoutRequest,
    user: Annotated[User, Depends(signed_in)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    paypal: Annotated[PayPalClient, Depends(get_paypal)],
) -> dict:
    """Creates a PayPal subscription and returns the page where the buyer approves it."""
    plan = get_plan(req.plan)
    plan_id = plan.billing_plan_id(req.interval)
    if not plan_id:
        raise HTTPException(
            503,
            {"code": "config", "message": f"No PayPal {req.interval}ly plan for {plan.name}"},
        )
    base = settings.public_url.rstrip("/")
    try:
        sub_id, url = paypal.create_subscription(
            plan_id=plan_id,
            user_id=user.id,
            quantity=req.seats if plan.per_seat else 1,
            return_url=f"{base}/billing/done?status=success",
            cancel_url=f"{base}/billing/done?status=cancel",
        )
    except PayPalError as e:
        raise HTTPException(502, {"code": "billing_error", "message": str(e)}) from e
    # Remember it now so the return page / webhook can find the account either way.
    user.billing_subscription_id = sub_id
    user.subscription_status = "approval_pending"
    db.commit()
    return {"url": url}


@router.post("/v1/billing/portal")
def portal(
    user: Annotated[User, Depends(signed_in)],
    paypal: Annotated[PayPalClient, Depends(get_paypal)],
) -> dict:
    """PayPal has no merchant portal: subscribers manage or cancel in their PayPal account."""
    if not user.billing_subscription_id:
        raise HTTPException(
            400, {"code": "no_subscription", "message": "You don't have a subscription yet."}
        )
    return {"url": paypal.manage_url}


@router.post("/v1/billing/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    paypal: Annotated[PayPalClient, Depends(get_paypal)],
) -> dict:
    if not settings.paypal_webhook_id:
        raise HTTPException(503, {"code": "config", "message": "PAYPAL_WEBHOOK_ID is not set"})
    raw = await request.body()
    try:
        ok = paypal.verify_webhook(request.headers, raw, settings.paypal_webhook_id)
    except PayPalError as e:
        raise HTTPException(502, {"code": "billing_error", "message": str(e)}) from e
    if not ok:
        raise HTTPException(400, {"code": "bad_signature", "message": "Not from PayPal"})
    return {"outcome": billing.handle_event(db, json.loads(raw))}


@router.get("/billing/done", response_class=HTMLResponse, include_in_schema=False)
def billing_done(
    db: Annotated[Session, Depends(get_db)],
    paypal: Annotated[PayPalClient | None, Depends(optional_paypal)],
    status: str = "",
    subscription_id: str | None = None,
) -> HTMLResponse:
    """Where PayPal sends the buyer back. Reads the subscription from PayPal (never trusting
    the URL) so Pro is on right away, even if the webhook comes later."""
    if status == "success" and subscription_id and paypal is not None:
        try:
            billing.apply_subscription(db, paypal.get_subscription(subscription_id))
        except PayPalError as e:
            log.warning("could not confirm subscription on return: %s", e)
    msg = {
        "success": "Thanks. Your plan is active.",
        "cancel": "No problem. Nothing was charged.",
    }.get(status, "You're all set.")
    return HTMLResponse(
        page(
            "Nudgy",
            f"""<h1>{escape(msg)}</h1>
<p><a class="btn" href="nudgy://billing?status={escape(status)}">Back to Nudgy</a></p>""",
        )
    )
