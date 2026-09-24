"""Who may run how many lessons, decided only here (never by the desktop app).

- One global date, FREE_UNTIL = LAUNCH_DATE + 365 days (or an admin override). Before it,
  every account has unlimited use and nothing about limits or payment is sent to the app,
  except a quiet notice in the last 30 days.
- From FREE_UNTIL on, free accounts get FREE_TIER_LESSONS_PER_MONTH new lessons per calendar
  month (UTC). Lessons run before FREE_UNTIL don't count. Paid plans are never capped.
- Questions, lesson step checks, reviews and walkthrough replays are never capped; they're
  only logged (usage.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AppSetting, User
from app.services.plans import get_plan
from app.services.usage import effective_plan, month_start, next_month, used_since

FREE_YEAR = timedelta(days=365)
NOTICE_WINDOW = timedelta(days=30)

LESSONS_KEY = "free_tier_lessons_per_month"
FREE_UNTIL_KEY = "free_until_override"


def _get(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else None


def _put(db: Session, key: str, value: str | None) -> None:
    row = db.get(AppSetting, key)
    if value is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def free_until(db: Session, s: Settings) -> tuple[datetime | None, str | None]:
    """(when unlimited access ends, where that came from). None = no free window."""
    if row := _get(db, FREE_UNTIL_KEY):
        return _midnight(date.fromisoformat(row)), "admin"
    if s.free_until_override:
        return _midnight(s.free_until_override), "env_override"
    if s.launch_date:
        return _midnight(s.launch_date) + FREE_YEAR, "launch_date"
    return None, None


def set_free_until(db: Session, d: date | None) -> None:
    _put(db, FREE_UNTIL_KEY, d.isoformat() if d else None)


def lessons_per_month(db: Session, s: Settings) -> int:
    """The runtime row wins; the env value only seeds it the first time."""
    row = _get(db, LESSONS_KEY)
    if row is None:
        _put(db, LESSONS_KEY, str(s.free_tier_lessons_per_month))
        return s.free_tier_lessons_per_month
    return int(row)


def set_lessons_per_month(db: Session, n: int) -> None:
    _put(db, LESSONS_KEY, str(n))


def is_paid(db: Session, user: User) -> bool:
    return get_plan(effective_plan(db, user)).paid


@dataclass(frozen=True)
class Quota:
    used: int
    limit: int
    resets_at: datetime

    @property
    def left(self) -> int:
        return max(0, self.limit - self.used)

    def as_dict(self) -> dict:
        return {
            "used": self.used,
            "limit": self.limit,
            "left": self.left,
            "resets_at": self.resets_at.isoformat(),
        }


def lesson_quota(db: Session, s: Settings, user: User | None, now: datetime) -> Quota | None:
    """The user's monthly lesson allowance, or None if they aren't capped right now."""
    if user is None or is_paid(db, user):
        return None
    end, _ = free_until(db, s)
    if end is not None and now < end:
        return None
    start = month_start(now)
    if end is not None and end > start:
        start = end  # lessons from the free window don't count against the first month
    return Quota(
        used=used_since(db, user, "lessons", start),
        limit=lessons_per_month(db, s),
        resets_at=next_month(month_start(now)),
    )


def state(db: Session, s: Settings, user: User | None, now: datetime) -> dict:
    """What the app may show. Before the notice window this is all empty on purpose."""
    end, _ = free_until(db, s)
    paid = user is not None and is_paid(db, user)
    notice = end is not None and not paid and end - NOTICE_WINDOW <= now < end
    quota = lesson_quota(db, s, user, now)
    return {
        "notice": {
            "free_until": end.date().isoformat(),
            "lessons_per_month": lessons_per_month(db, s),
        }
        if notice
        else None,
        "capped": quota is not None,
        "lessons": quota.as_dict() if quota else None,
    }
