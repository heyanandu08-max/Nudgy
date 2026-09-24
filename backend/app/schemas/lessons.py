"""Tutor mode wire format."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.ask import (
    ActionHint,
    ElementTarget,
    ForegroundApp,
    PointTarget,
    ScreenshotInfo,
    UiElement,
)


class StepTarget(BaseModel):
    role: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=200)


class LessonStep(BaseModel):
    instruction: str = Field(min_length=1, max_length=600)
    target: StepTarget | None = None
    action_hint: ActionHint | None = None
    success_check: str = Field(min_length=1, max_length=600)
    why: str = Field(default="", max_length=600)


class LessonPlan(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    app: str = Field(default="", max_length=100)
    skill: str = Field(min_length=1, max_length=100)
    skill_name: str = Field(min_length=1, max_length=200)
    steps: list[LessonStep] = Field(min_length=1, max_length=15)


class LessonQuota(BaseModel):
    used: int
    limit: int
    left: int
    resets_at: str


class PlannedLesson(LessonPlan):
    """The plan as sent to the app, plus the monthly allowance when the user is capped."""

    quota: LessonQuota | None = None


LESSON_PLAN_SCHEMA = (
    '{"title": "...", "app": "...", "skill": "...", "skill_name": "...", "steps": '
    '[{"instruction": "...", "target": {"role": "...", "name": "..."} | null, '
    '"action_hint": "click" | "type" | "drag" | "look" | null, "success_check": "...", "why": "..."}]}'
)


class ScreenState(BaseModel):
    app: ForegroundApp | None = None
    elements: list[UiElement] = Field(default_factory=list, max_length=400)


class PlanContext(ScreenState):
    goal: str = Field(min_length=1, max_length=500)
    screenshot: ScreenshotInfo | None = None
    language: str = Field(default="en", max_length=16)


class VerifyContext(BaseModel):
    step: LessonStep
    before: ScreenState
    after: ScreenState
    screenshot: ScreenshotInfo | None = None  # the "after" screenshot
    attempt: int = Field(default=1, ge=1, le=50)
    language: str = Field(default="en", max_length=16)


class VerifyResult(BaseModel):
    passed: bool
    hint: str = Field(default="", max_length=600)


VERIFY_SCHEMA = '{"passed": true | false, "hint": "..."}'


class LocateContext(ScreenState):
    target: StepTarget | None = None
    description: str = Field(default="", max_length=600)
    screenshot: ScreenshotInfo | None = None


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    voice_id: str | None = Field(default=None, max_length=64)
    language: str = Field(default="en", max_length=16)


class LocateResult(BaseModel):
    target: ElementTarget | PointTarget | None = None


LOCATE_SCHEMA = '{"target": {"element_id": "e12"} | {"x": 812, "y": 64} | null}'
