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


@lru_cache
def _translations() -> dict:
    return load_yaml("packs_i18n.yaml")


def localized(pack: Pack, lang: str) -> Pack:
    """Title, summary and lesson titles in `lang` where translated; goals stay as they are."""
    t = _translations().get(lang, {}).get(pack.id)
    if not t:
        return pack
    names = t.get("lessons", {})
    return pack.model_copy(
        update={
            "title": t.get("title", pack.title),
            "summary": t.get("summary", pack.summary),
            "lessons": [
                lesson.model_copy(update={"title": names.get(lesson.id, lesson.title)})
                for lesson in pack.lessons
            ],
        }
    )


@router.get("/packs", response_model=list[Pack])
def packs(platform: Literal["windows", "mac"] | None = None, lang: str = "en") -> list[Pack]:
    """Courses for the caller's OS (all of them when `platform` is left out), in `lang`."""
    return [
        localized(p, lang)
        for p in all_packs()
        if platform is None or p.platform in (None, platform)
    ]
