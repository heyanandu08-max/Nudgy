"""Per-request usage metering and monthly plan limits (metadata only)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Team, UsageEvent, User
from app.services.plans import KINDS, get_plan


class LimitReached(Exception):
    def __init__(self, kind: str, limit: int, plan: str):
        super().__init__(f"{kind} limit {limit} reached on {plan}")
        self.kind, self.limit, self.plan = kind, limit, plan


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def effective_plan(db: Session, user: User) -> str:
    """Team members use the team plan while their team exists."""
    if user.team_id is not None and db.get(Team, user.team_id) is not None:
        return "team"
    return user.plan


def used_this_month(db: Session, user: User, kind: str, now: datetime | None = None) -> int:
    return (
        db.scalar(
            select(func.count(UsageEvent.id)).where(
                UsageEvent.user_id == user.id,
                UsageEvent.kind == kind,
                UsageEvent.at >= month_start(now),
            )
        )
        or 0
    )


def check_and_record(db: Session, user: User, kind: str) -> UsageEvent:
    """Raises LimitReached, else records the call and returns the event (to add tokens later)."""
    plan_id = effective_plan(db, user)
    limit = get_plan(plan_id).limit(kind)
    if limit is not None and used_this_month(db, user, kind) >= limit:
        raise LimitReached(kind, limit, plan_id)
    ev = UsageEvent(user_id=user.id, kind=kind)
    db.add(ev)
    db.commit()
    return ev


def summary(db: Session, user: User) -> dict:
    plan_id = effective_plan(db, user)
    plan = get_plan(plan_id)
    return {
        "plan": plan_id,
        "plan_name": plan.name,
        "usage": {k: used_this_month(db, user, k) for k in KINDS},
        "limits": {k: plan.limit(k) for k in KINDS},
        "resets_at": _next_month(month_start()).isoformat(),
    }


def _next_month(d: datetime) -> datetime:
    return d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)


def finish(event_id: int, tokens_in: int, tokens_out: int, latency_ms: int) -> None:
    """Adds token/latency metadata once a streamed request is done (own session: the
    request's session is already closed by then)."""
    from app.db import _sessionmaker

    with _sessionmaker()() as db:
        ev = db.get(UsageEvent, event_id)
        if ev is not None:
            ev.tokens_in, ev.tokens_out, ev.latency_ms = tokens_in, tokens_out, latency_ms
            db.commit()
