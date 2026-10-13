"""The .nudgy walkthrough document (JSON). Shared by the app (serde) and the backend."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.ask import ActionHint
from app.schemas.lessons import StepTarget

FORMAT = "nudgy.walkthrough"
MAX_SCREENSHOT_CHARS = 400_000  # ~300 KB JPEG as a data URL


class RawStep(BaseModel):
    """What the recorder saw, before cleaning."""

    kind: Literal["click", "type", "shortcut", "key"]
    target: StepTarget | None = None
    text: str | None = Field(default=None, max_length=2000)  # typed text ("[hidden]" for secrets)
    keys: str | None = Field(default=None, max_length=64)  # e.g. "Ctrl+B", "Enter"
    app: str = Field(default="", max_length=200)
    window: str = Field(default="", max_length=300)
    note: str | None = Field(default=None, max_length=1000)


class WalkthroughStep(BaseModel):
    instruction: str = Field(min_length=1, max_length=600)
    target: StepTarget | None = None
    action_hint: ActionHint | None = None
    success_check: str = Field(default="", max_length=600)
    why: str = Field(default="", max_length=600)
    note: str | None = Field(default=None, max_length=1000)
    screenshot: str | None = None  # data:image/jpeg;base64,… (optional)
    raw: list[int] = Field(default_factory=list)  # indices into the raw log

    @field_validator("screenshot")
    @classmethod
    def data_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.startswith("data:image/jpeg;base64,") or len(v) > MAX_SCREENSHOT_CHARS:
            raise ValueError("screenshot must be a JPEG data URL under 300 KB")
        return v


class Walkthrough(BaseModel):
    format: Literal["nudgy.walkthrough"] = FORMAT
    version: int = 1
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    app: str = Field(default="", max_length=100)
    summary: str = Field(default="", max_length=1000)
    platform: str = Field(default="", max_length=16)
    created_at: int = 0
    steps: list[WalkthroughStep] = Field(min_length=1, max_length=100)

    def without_screenshots(self) -> Walkthrough:
        return self.model_copy(
            update={"steps": [s.model_copy(update={"screenshot": None}) for s in self.steps]}
        )


class CleanRequest(BaseModel):
    raw: list[RawStep] = Field(min_length=1, max_length=300)
    app: str = Field(default="", max_length=100)
    language: str = Field(default="en", max_length=16)


class CleanedStep(BaseModel):
    instruction: str = Field(min_length=1, max_length=600)
    target: StepTarget | None = None
    action_hint: ActionHint | None = None
    success_check: str = Field(default="", max_length=600)
    why: str = Field(default="", max_length=600)
    raw: list[int] = Field(default_factory=list)


class CleanedWalkthrough(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    app: str = Field(default="", max_length=100)
    summary: str = Field(default="", max_length=1000)
    steps: list[CleanedStep] = Field(min_length=1, max_length=100)


CLEANED_SCHEMA = (
    '{"title": "...", "app": "...", "summary": "...", "steps": [{"instruction": "...", '
    '"target": {"role": "...", "name": "..."} | null, "action_hint": "click" | "type" | "drag" | "look" | null, '
    '"success_check": "...", "why": "...", "raw": [0, 1]}]}'
)


class ShareRequest(BaseModel):
    walkthrough: Walkthrough
    include_screenshots: bool = False
    team: bool = False  # also list it in the team library


class ShareResponse(BaseModel):
    slug: str
    url: str
