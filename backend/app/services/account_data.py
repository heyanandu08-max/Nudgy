"""Everything the server holds about one user: export it, or delete it (GDPR-style rights).

The server never has screenshots or audio (they are processed in memory per request), so this
is account, usage metadata, team membership and walkthroughs the user chose to share.
"""

import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import SharedWalkthrough, Team, TeamInvite, UsageEvent, User

log = logging.getLogger("nudgy.account")


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def export(db: Session, user: User) -> dict:
    team = db.get(Team, user.team_id) if user.team_id else None
    usage = db.scalars(
        select(UsageEvent).where(UsageEvent.user_id == user.id).order_by(UsageEvent.at)
    ).all()
    shared = db.scalars(
        select(SharedWalkthrough)
        .where(SharedWalkthrough.owner_id == user.id)
        .order_by(SharedWalkthrough.created_at)
    ).all()
    return {
        "format": "nudgy-account-export",
        "version": 1,
        "account": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "plan": user.plan,
            "subscription_status": user.subscription_status,
            "has_subscription": user.billing_subscription_id is not None,
            "paid_until": _iso(user.paid_until),
            "created_at": _iso(user.created_at),
        },
        "team": {"id": team.id, "name": team.name, "owner": team.owner_id == user.id}
        if team
        else None,
        "usage": [
            {
                "kind": u.kind,
                "at": _iso(u.at),
                "tokens_in": u.tokens_in,
                "tokens_out": u.tokens_out,
                "latency_ms": u.latency_ms,
            }
            for u in usage
        ],
        "shared_walkthroughs": [
            {
                "slug": w.slug,
                "title": w.title,
                "app": w.app,
                "views": w.views,
                "created_at": _iso(w.created_at),
                "document": json.loads(w.document),
            }
            for w in shared
        ],
    }


def delete_user(db: Session, user: User) -> dict:
    """Removes the user and everything tied to them. A team they own is dissolved:
    members drop back to the free plan and the team's shared library goes with it."""
    removed = {"usage": 0, "walkthroughs": 0, "team_dissolved": False}
    team = db.get(Team, user.team_id) if user.team_id else None
    if team and team.owner_id == user.id:
        for member in db.scalars(select(User).where(User.team_id == team.id)):
            member.team_id = None
            if member.id != user.id:
                member.plan = "free"
        db.execute(delete(TeamInvite).where(TeamInvite.team_id == team.id))
        removed["walkthroughs"] += db.execute(
            delete(SharedWalkthrough).where(SharedWalkthrough.team_id == team.id)
        ).rowcount
        db.delete(team)
        removed["team_dissolved"] = True
    removed["walkthroughs"] += db.execute(
        delete(SharedWalkthrough).where(SharedWalkthrough.owner_id == user.id)
    ).rowcount
    removed["usage"] = db.execute(delete(UsageEvent).where(UsageEvent.user_id == user.id)).rowcount
    db.execute(delete(TeamInvite).where(TeamInvite.email == user.email))
    db.delete(user)
    db.commit()
    log.info("deleted account id=%s %s", user.id, removed)
    return removed
