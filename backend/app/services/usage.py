"""Quiet per-request usage log (metadata only) for cost tracking and the lesson cap.

Every AI call by a signed-in user is recorded with tokens, latency, audio length and TTS
characters, whatever the plan or phase. Only `lessons` is ever limited (see access.py).
"""

from __future__ import annotations

import io
import wave
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Team, UsageEvent, User

KINDS = ("asks", "lessons", "lesson_calls", "speak", "transcribe")


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(d: datetime) -> datetime:
    return d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)


def effective_plan(db: Session, user: User) -> str:
    """Team members use the team plan while their team exists."""
    if user.team_id is not None and db.get(Team, user.team_id) is not None:
        return "team"
    return user.plan


def used_since(db: Session, user: User, kind: str, since: datetime) -> int:
    return (
        db.scalar(
            select(func.count(UsageEvent.id)).where(
                UsageEvent.user_id == user.id,
                UsageEvent.kind == kind,
                UsageEvent.at >= since,
            )
        )
        or 0
    )


def record(
    db: Session, user: User, kind: str, now: datetime | None = None, **meta: int
) -> UsageEvent:
    ev = UsageEvent(user_id=user.id, kind=kind, at=now or datetime.now(UTC), **meta)
    db.add(ev)
    db.commit()
    return ev


def refund(db: Session, event: UsageEvent | None) -> None:
    """Drops an event whose call failed (a lesson that never got a plan doesn't count)."""
    if event is not None:
        db.delete(event)
        db.commit()


def finish(event_id: int, tokens_in: int, tokens_out: int, latency_ms: int, **meta: int) -> None:
    """Adds token/latency metadata once a (streamed) request is done. Own session: a streamed
    request's session is already closed by then."""
    from app.db import _sessionmaker

    with _sessionmaker()() as db:
        ev = db.get(UsageEvent, event_id)
        if ev is not None:
            ev.tokens_in, ev.tokens_out, ev.latency_ms = tokens_in, tokens_out, latency_ms
            for k, v in meta.items():
                setattr(ev, k, v)
            db.commit()


def wav_ms(data: bytes | None) -> int:
    """Duration of a WAV upload, for STT cost tracking; 0 if it isn't a readable WAV."""
    if not data:
        return 0
    try:
        with wave.open(io.BytesIO(data)) as w:
            return int(w.getnframes() * 1000 / max(1, w.getframerate()))
    except (wave.Error, EOFError):
        return 0
