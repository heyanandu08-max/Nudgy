from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class SharedWalkthrough(Base):
    __tablename__ = "shared_walkthroughs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    app: Mapped[str] = mapped_column(String(100), default="")
    document: Mapped[str] = mapped_column(Text)  # the .nudgy JSON
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WalkthroughRun(Base):
    """A team member's run through a team walkthrough, for the owner's onboarding report.
    Metadata only: no screenshots, no audio, nothing typed."""

    __tablename__ = "walkthrough_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    walkthrough_id: Mapped[int] = mapped_column(
        ForeignKey("shared_walkthroughs.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16))  # completed | abandoned
    steps_total: Mapped[int] = mapped_column(Integer)
    steps_passed: Mapped[int] = mapped_column(Integer)
    hints: Mapped[int] = mapped_column(Integer, default=0)
    stuck_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TeamCourse(Base):
    """An owner's onboarding course: an ordered list of the team's shared walkthroughs."""

    __tablename__ = "team_courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(500), default="")
    slugs: Mapped[str] = mapped_column(Text, default="[]")  # JSON list, in order
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
