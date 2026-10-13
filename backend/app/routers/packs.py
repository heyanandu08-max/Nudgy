"""Courses ("lesson packs"): curated, ordered lessons per app, from config/packs.yaml."""

from functools import lru_cache
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import load_yaml

router = APIRouter(prefix="/v1")


class PackLesson(BaseModel):
    id: str
    title: str
    goal: str


class Pack(BaseModel):
    id: str
    title: str
    app: str
    summary: str
    platform: Literal["windows", "mac"] | None = None
    lessons: list[PackLesson]


@lru_cache
def all_packs() -> tuple[Pack, ...]:
    return tuple(Pack(**p) for p in load_yaml("packs.yaml")["packs"])


@router.get("/packs", response_model=list[Pack])
def packs(platform: Literal["windows", "mac"] | None = None) -> list[Pack]:
    """Courses for the caller's OS (all of them when `platform` is left out)."""
    return [p for p in all_packs() if platform is None or p.platform in (None, platform)]
