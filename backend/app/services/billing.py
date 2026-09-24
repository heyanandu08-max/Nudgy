"""Applies Stripe webhook events to accounts (idempotent)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StripeEvent, Team, User
from app.services.plans import plan_for_price

log = logging.getLogger("nudgy.billing")

ACTIVE = {"active", "trialing"}


def _user_for(db: Session, obj: dict) -> User | None:
    uid = (obj.get("metadata") or {}).get("user_id") or obj.get("client_reference_id")
    if uid:
        user = db.get(User, int(uid))
        if user:
            return user
    customer = obj.get("customer")
    return db.scalar(select(User).where(User.stripe_customer_id == customer)) if customer else None


def _set_plan(db: Session, user: User, plan: str, quantity: int = 1) -> None:
    user.plan = plan
    if plan == "team":
        team = db.get(Team, user.team_id) if user.team_id else None
        if team is None:
            team = Team(name=f"{user.email.split('@')[0]}'s team", owner_id=user.id, seats=quantity)
            db.add(team)
            db.flush()
            user.team_id = team.id
        elif team.owner_id == user.id:
            team.seats = quantity


def _subscription_plan(sub: dict) -> tuple[str | None, int]:
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return (sub.get("metadata") or {}).get("plan"), 1
    item = items[0]
    return plan_for_price((item.get("price") or {}).get("id")) or (sub.get("metadata") or {}).get(
        "plan"
    ), int(item.get("quantity") or 1)


def handle_event(db: Session, event: dict) -> str:
    """Returns what happened (for logs/tests)."""
    if db.get(StripeEvent, event["id"]) is not None:
        return "duplicate"
    etype = event["type"]
    obj = event["data"]["object"]
    outcome = "ignored"
    user = _user_for(db, obj)

    if etype == "checkout.session.completed" and user:
        user.stripe_customer_id = obj.get("customer") or user.stripe_customer_id
        user.stripe_subscription_id = obj.get("subscription") or user.stripe_subscription_id
        user.subscription_status = "active"
        plan = (obj.get("metadata") or {}).get("plan", "pro")
        _set_plan(db, user, plan, int((obj.get("metadata") or {}).get("seats", 1)))
        outcome = f"upgraded:{plan}"
    elif etype in ("customer.subscription.created", "customer.subscription.updated") and user:
        user.stripe_subscription_id = obj.get("id")
        user.subscription_status = obj.get("status")
        plan, qty = _subscription_plan(obj)
        if obj.get("status") in ACTIVE and plan:
            _set_plan(db, user, plan, qty)
            outcome = f"plan:{plan}"
        elif obj.get("status") in ("canceled", "unpaid", "incomplete_expired"):
            user.plan = "free"
            outcome = "downgraded"
        else:
            outcome = f"status:{obj.get('status')}"
    elif etype == "customer.subscription.deleted" and user:
        user.plan = "free"
        user.subscription_status = "canceled"
        outcome = "downgraded"
    elif etype == "invoice.payment_failed" and user:
        user.subscription_status = "past_due"  # Stripe retries; plan stays until canceled
        outcome = "past_due"

    db.add(StripeEvent(id=event["id"], type=etype))
    db.commit()
    log.info("stripe %s %s → %s", etype, event["id"], outcome)
    return outcome
