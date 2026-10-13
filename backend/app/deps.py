"""Shared FastAPI dependencies: who is calling, the clock, and usage metering."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import UsageEvent, User
from app.services import access
from app.services.auth import AuthError, user_id_from_session
from app.services.usage import record


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


def get_clock() -> Callable[[], datetime]:
    """The server's clock (UTC). Tests override it to step across FREE_UNTIL and months."""
    return lambda: datetime.now(UTC)


def metered(kind: str):
    """Logs one call of `kind` for cost tracking. For `lessons` it first enforces the free-tier
    monthly cap (402 `limit_reached`); nothing else is ever limited."""

    def dep(
        user: Annotated[User | None, Depends(current_user)],
        db: Annotated[Session, Depends(get_db)],
        settings: Annotated[Settings, Depends(get_settings)],
        clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    ) -> UsageEvent | None:
        if user is None:
            return None
        now = clock()
        if kind == "lessons":
            quota = access.lesson_quota(db, settings, user, now)
            if quota is not None and quota.left == 0:
                raise HTTPException(
                    402,
                    {
                        "code": "limit_reached",
                        "message": "This month's free lessons are used up.",
                        "kind": kind,
                        **quota.as_dict(),
                    },
                )
        return record(db, user, kind, now)

    return dep
