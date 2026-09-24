"""Shared FastAPI dependencies: who is calling, and metering against their plan."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import UsageEvent, User
from app.services.auth import AuthError, user_id_from_session
from app.services.usage import LimitReached, check_and_record


def optional_user(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        uid = user_id_from_session(settings, authorization[7:].strip())
    except AuthError as e:
        raise HTTPException(
            401, {"code": "auth_expired", "message": "Please sign in again."}
        ) from e
    user = db.get(User, uid)
    if user is None:
        raise HTTPException(401, {"code": "auth_expired", "message": "Please sign in again."})
    return user


def current_user(
    user: Annotated[User | None, Depends(optional_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User | None:
    """The signed-in user; anonymous is allowed only when NUDGY_AUTH_REQUIRED is false (dev)."""
    if user is None and settings.auth_required:
        raise HTTPException(401, {"code": "auth_required", "message": "Please sign in."})
    return user


def signed_in(user: Annotated[User | None, Depends(optional_user)]) -> User:
    """Endpoints that only make sense with an account (billing, teams, /v1/me)."""
    if user is None:
        raise HTTPException(401, {"code": "auth_required", "message": "Please sign in."})
    return user


def metered(kind: str):
    """Counts one call of `kind` against the caller's monthly plan limit (402 when used up)."""

    def dep(
        user: Annotated[User | None, Depends(current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> UsageEvent | None:
        if user is None:
            return None
        try:
            return check_and_record(db, user, kind)
        except LimitReached as e:
            raise HTTPException(
                402,
                {
                    "code": "limit_reached",
                    "message": f"You've used this month's {e.kind.replace('_', ' ')} on the {e.plan} plan.",
                    "kind": e.kind,
                    "limit": e.limit,
                    "plan": e.plan,
                },
            ) from e

    return dep
