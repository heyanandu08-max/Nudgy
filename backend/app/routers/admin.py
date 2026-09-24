"""Operator-only endpoints (header X-Admin-Token = NUDGY_ADMIN_TOKEN; 404 when unset).

- /v1/admin/access   read/change FREE_UNTIL and the free-tier lesson cap without a redeploy
- /v1/admin/users/{email}/plan   set a plan by hand (QA of paid vs free before billing exists)
- /v1/admin/usage    monthly cost and lessons-per-user figures, to pick a sane cap
"""

import secrets
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_clock
from app.models import UsageEvent, User
from app.services import access
from app.services.usage import month_start, next_month

router = APIRouter(prefix="/v1/admin")


def admin(
    settings: Annotated[Settings, Depends(get_settings)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.admin_token:
        raise HTTPException(404, "Not Found")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(403, {"code": "forbidden", "message": "Bad admin token."})


def _config(db: Session, s: Settings) -> dict:
    end, source = access.free_until(db, s)
    return {
        "launch_date": s.launch_date.isoformat() if s.launch_date else None,
        "free_until": end.date().isoformat() if end else None,
        "free_until_source": source,
        "free_tier_lessons_per_month": access.lessons_per_month(db, s),
    }


class AccessUpdate(BaseModel):
    # Omit a field to leave it; `free_until: null` clears the admin override.
    free_until: date | None = None
    free_tier_lessons_per_month: int | None = Field(default=None, ge=0, le=10_000)


@router.get("/access", dependencies=[Depends(admin)])
def get_access(
    db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)]
) -> dict:
    return _config(db, settings)


@router.put("/access", dependencies=[Depends(admin)])
def put_access(
    body: AccessUpdate,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if "free_until" in body.model_fields_set:
        if body.free_until and settings.launch_date and body.free_until < settings.launch_date:
            raise HTTPException(422, {"code": "bad_date", "message": "Before the launch date."})
        access.set_free_until(db, body.free_until)
    if body.free_tier_lessons_per_month is not None:
        access.set_lessons_per_month(db, body.free_tier_lessons_per_month)
    return _config(db, settings)


class PlanUpdate(BaseModel):
    plan: Literal["free", "pro", "team"]


@router.put("/users/{email}/plan", dependencies=[Depends(admin)])
def put_plan(email: str, body: PlanUpdate, db: Annotated[Session, Depends(get_db)]) -> dict:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise HTTPException(404, {"code": "not_found", "message": "No such user."})
    user.plan = body.plan
    db.commit()
    return {"email": user.email, "plan": user.plan}


def _pct(values: list[int], p: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    return s[min(len(s) - 1, int(p * len(s)))]


@router.get("/usage", dependencies=[Depends(admin)])
def usage_report(
    db: Annotated[Session, Depends(get_db)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    months: int = 3,
) -> list[dict]:
    """Newest month first. `lessons_per_user` covers every user active that month (zeros too)."""
    firsts = [month_start(clock())]
    for _ in range(max(0, min(months, 24) - 1)):
        prev = firsts[-1]
        firsts.append(
            prev.replace(year=prev.year - 1, month=12)
            if prev.month == 1
            else prev.replace(month=prev.month - 1)
        )
    events = db.scalars(select(UsageEvent).where(UsageEvent.at >= firsts[-1])).all()
    out = []
    for first in firsts:
        end = next_month(first)
        month = [e for e in events if first <= _aware(e.at) < end]
        per_user: dict[int, int] = defaultdict(int)
        kinds: dict[str, int] = defaultdict(int)
        for e in month:
            kinds[e.kind] += 1
            per_user.setdefault(e.user_id, 0)
            if e.kind == "lessons":
                per_user[e.user_id] += 1
        lessons = list(per_user.values())
        out.append(
            {
                "month": first.strftime("%Y-%m"),
                "active_users": len(per_user),
                "calls": dict(kinds),
                "tokens_in": sum(e.tokens_in for e in month),
                "tokens_out": sum(e.tokens_out for e in month),
                "stt_minutes": round(sum(e.audio_ms for e in month) / 60000, 1),
                "tts_chars": sum(e.tts_chars for e in month),
                "lessons_per_user": {
                    "p50": _pct(lessons, 0.5),
                    "p90": _pct(lessons, 0.9),
                    "max": max(lessons, default=0),
                },
            }
        )
    return out


def _aware(d: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything here is UTC."""
    return d if d.tzinfo else d.replace(tzinfo=UTC)
