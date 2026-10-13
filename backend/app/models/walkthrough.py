from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
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
