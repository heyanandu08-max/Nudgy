"""Applies PayPal subscription state to accounts (idempotent).

Two ways in, same result: the webhook (PayPal tells us) and the return page (the buyer comes
back from PayPal and we read the subscription). Either one activating first is fine.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BillingEvent, Team, User
from app.services.plans import plan_for_price

log = logging.getLogger("nudgy.billing")


def _user_for(db: Session, sub: dict) -> User | None:
    uid = sub.get("custom_id")
    if uid and str(uid).isdigit():
        user = db.get(User, int(uid))
        if user:
            return user
    sid = sub.get("id")
    return db.scalar(select(User).where(User.billing_subscription_id == sid)) if sid else None


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


def _paid_through(sub: dict) -> datetime | None:
    """When the period already paid for ends (PayPal's next billing time)."""
    raw = (sub.get("billing_info") or {}).get("next_billing_time")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)  # Python 3.11+ reads the "Z" suffix
    except ValueError:
        return None


def apply_subscription(db: Session, sub: dict) -> str:
    """Brings the account in line with a PayPal subscription resource. Returns the outcome."""
    user = _user_for(db, sub)
    if user is None:
        return "no_user"
    status = (sub.get("status") or "").upper()
    plan = plan_for_price(sub.get("plan_id"))
    user.billing_subscription_id = sub.get("id") or user.billing_subscription_id
    if status == "ACTIVE" and plan:
        _set_plan(db, user, plan, int(sub.get("quantity") or 1))
        user.subscription_status, user.paid_until = "active", None
        outcome = f"active:{plan}"
    elif status == "CANCELLED":
        # No more payments, but they keep what they paid for until the period ends.
        user.subscription_status = "canceled"
        user.paid_until = _paid_through(sub) or datetime.now(UTC)
        outcome = "canceled"
    elif status in ("EXPIRED", "SUSPENDED"):
        user.plan, user.subscription_status, user.paid_until = "free", status.lower(), None
        outcome = "downgraded"
    else:  # APPROVAL_PENDING, APPROVED: not paid yet
        user.subscription_status = status.lower() or None
        outcome = f"status:{status.lower()}"
    db.commit()
    return outcome


def handle_event(db: Session, event: dict) -> str:
    """A verified PayPal webhook event. Returns what happened (for logs/tests)."""
    if db.get(BillingEvent, event["id"]) is not None:
        return "duplicate"
    etype = event.get("event_type", "")
    res = event.get("resource") or {}
    outcome = "ignored"
    if etype.startswith("BILLING.SUBSCRIPTION."):
        if etype == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
            user = _user_for(db, res)
            if user:  # PayPal retries; the plan stays until it suspends the subscription
                user.subscription_status = "past_due"
                outcome = "past_due"
        else:
            outcome = apply_subscription(db, res)
    elif etype == "PAYMENT.SALE.COMPLETED":
        # A renewal went through: the linked subscription is (still) active.
        sid = res.get("billing_agreement_id")
        user = db.scalar(select(User).where(User.billing_subscription_id == sid)) if sid else None
        if user and user.subscription_status == "past_due":
            user.subscription_status = "active"
        outcome = "renewed" if user else "ignored"
    db.add(BillingEvent(id=event["id"], type=etype[:80]))
    db.commit()
    log.info("paypal %s %s → %s", etype, event["id"], outcome)
    return outcome
