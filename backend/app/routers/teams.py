"""Team plan: members, invites, and the shared walkthrough library (onboarding use case)."""

import json
from collections import Counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import signed_in
from app.models import SharedWalkthrough, Team, TeamInvite, User, WalkthroughRun
from app.routers.auth import get_mailer
from app.services.email import EmailSender

router = APIRouter(prefix="/v1/team")


def _team(db: Session, user: User) -> Team:
    team = db.get(Team, user.team_id) if user.team_id else None
    if team is None:
        raise HTTPException(403, {"code": "no_team", "message": "You're not on a team plan."})
    return team


def _owner(db: Session, user: User) -> Team:
    team = _team(db, user)
    if team.owner_id != user.id:
        raise HTTPException(
            403, {"code": "not_owner", "message": "Only the team owner can do that."}
        )
    return team


@router.get("")
def get_team(
    user: Annotated[User, Depends(signed_in)], db: Annotated[Session, Depends(get_db)]
) -> dict:
    team = _team(db, user)
    members = db.scalars(select(User).where(User.team_id == team.id).order_by(User.email)).all()
    invites = db.scalars(select(TeamInvite).where(TeamInvite.team_id == team.id)).all()
    return {
        "id": team.id,
        "name": team.name,
        "seats": team.seats,
        "owner": team.owner_id == user.id,
        "members": [
            {"id": m.id, "email": m.email, "owner": m.id == team.owner_id} for m in members
        ],
        "invites": [i.email for i in invites],
    }


class InviteRequest(BaseModel):
    email: EmailStr


@router.post("/invites")
def invite(
    req: InviteRequest,
    user: Annotated[User, Depends(signed_in)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    mailer: Annotated[EmailSender, Depends(get_mailer)],
) -> dict:
    team = _owner(db, user)
    email = req.email.lower()
    members = db.scalar(select(func.count(User.id)).where(User.team_id == team.id)) or 0
    pending = db.scalar(select(func.count(TeamInvite.id)).where(TeamInvite.team_id == team.id)) or 0
    if members + pending >= team.seats:
        raise HTTPException(
            409, {"code": "no_seats", "message": "All seats are taken. Add seats in billing."}
        )
    existing = db.scalar(select(User).where(User.email == email))
    if existing and existing.team_id == team.id:
        return {"invited": False, "reason": "already a member"}
    if (
        db.scalar(
            select(TeamInvite).where(TeamInvite.team_id == team.id, TeamInvite.email == email)
        )
        is None
    ):
        db.add(TeamInvite(team_id=team.id, email=email))
        db.commit()
    mailer.send(
        email,
        f"You're invited to {team.name} on Nudgy",
        f"{user.email} invited you to their Nudgy team. Install Nudgy and sign in with this email "
        f"address to join: {settings.public_url.rstrip('/')}",
    )
    return {"invited": True}


@router.delete("/members/{member_id}")
def remove_member(
    member_id: int,
    user: Annotated[User, Depends(signed_in)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    team = _owner(db, user)
    member = db.get(User, member_id)
    if member is None or member.team_id != team.id or member.id == team.owner_id:
        raise HTTPException(404, {"code": "not_found", "message": "No such member."})
    member.team_id = None
    member.plan = "free"
    db.execute(
        delete(WalkthroughRun).where(
            WalkthroughRun.team_id == team.id, WalkthroughRun.user_id == member.id
        )
    )
    db.commit()
    return {"removed": True}


@router.get("/walkthroughs")
def team_walkthroughs(
    user: Annotated[User, Depends(signed_in)], db: Annotated[Session, Depends(get_db)]
) -> list[dict]:
    team = _team(db, user)
    rows = db.scalars(
        select(SharedWalkthrough)
        .where(SharedWalkthrough.team_id == team.id)
        .order_by(SharedWalkthrough.created_at.desc())
    ).all()
    return [
        {"slug": r.slug, "title": r.title, "app": r.app, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


class RunReport(BaseModel):
    slug: str = Field(max_length=32)
    status: Literal["completed", "abandoned"]
    steps_total: int = Field(ge=0, le=500)
    steps_passed: int = Field(ge=0, le=500)
    hints: int = Field(default=0, ge=0, le=10_000)
    stuck_step: int | None = Field(default=None, ge=0, le=500)


@router.post("/runs")
def record_run(
    req: RunReport,
    user: Annotated[User, Depends(signed_in)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """A member finished (or gave up on) a walkthrough. Only kept when it is one of their
    team's walkthroughs; anything else is dropped."""
    w = db.scalar(select(SharedWalkthrough).where(SharedWalkthrough.slug == req.slug))
    if w is None or user.team_id is None or w.team_id != user.team_id:
        return {"recorded": False}
    db.add(
        WalkthroughRun(
            walkthrough_id=w.id,
            team_id=w.team_id,
            user_id=user.id,
            status=req.status,
            steps_total=req.steps_total,
            steps_passed=min(req.steps_passed, req.steps_total),
            hints=req.hints,
            stuck_step=req.stuck_step,
        )
    )
    db.commit()
    return {"recorded": True}


def _instructions(document: str) -> list[str]:
    try:
        return [str(s.get("instruction", "")) for s in json.loads(document).get("steps", [])]
    except (ValueError, AttributeError):
        return []


@router.get("/report")
def onboarding_report(
    user: Annotated[User, Depends(signed_in)], db: Annotated[Session, Depends(get_db)]
) -> list[dict]:
    """For the owner: per team walkthrough, who finished it, who hasn't started, and the
    steps people get stuck on."""
    team = _owner(db, user)
    members = db.scalars(select(User).where(User.team_id == team.id).order_by(User.email)).all()
    walkthroughs = db.scalars(
        select(SharedWalkthrough)
        .where(SharedWalkthrough.team_id == team.id)
        .order_by(SharedWalkthrough.created_at.desc())
    ).all()
    report = []
    for w in walkthroughs:
        runs = db.scalars(
            select(WalkthroughRun)
            .where(WalkthroughRun.walkthrough_id == w.id)
            .order_by(WalkthroughRun.at)
        ).all()
        latest: dict[int, WalkthroughRun] = {}
        finished: set[int] = set()
        for r in runs:
            latest[r.user_id] = r
            if r.status == "completed":
                finished.add(r.user_id)
        steps = _instructions(w.document)
        stuck = Counter(r.stuck_step for r in runs if r.stuck_step is not None)
        report.append(
            {
                "slug": w.slug,
                "title": w.title,
                "app": w.app,
                "members": [
                    {
                        "email": m.email,
                        "status": "completed"
                        if m.id in finished
                        else (latest[m.id].status if m.id in latest else "not_started"),
                        "last_at": latest[m.id].at.isoformat() if m.id in latest else None,
                    }
                    for m in members
                ],
                "stuck": [
                    {
                        "step": i,
                        "instruction": steps[i] if i < len(steps) else "",
                        "count": n,
                    }
                    for i, n in stuck.most_common(3)
                ],
            }
        )
    return report
