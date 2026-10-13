"""Team plan: members, invites, and the shared walkthrough library (onboarding use case)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import signed_in
from app.models import SharedWalkthrough, Team, TeamInvite, User
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
