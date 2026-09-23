"""Wire format for /v1/ask. JSON is snake_case end to end (Rust serde defaults)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ActionHint = Literal["click", "type", "drag", "look"]


class Box(BaseModel):
    x: float
    y: float
    w: float
    h: float


class UiElement(BaseModel):
    id: str = Field(max_length=16)
    role: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=200)
    rect: Box  # screenshot pixels


class ScreenshotInfo(BaseModel):
    width: int = Field(gt=0, le=4096)
    height: int = Field(gt=0, le=4096)


class ForegroundApp(BaseModel):
    name: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=300)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class AskContext(BaseModel):
    elements: list[UiElement] = Field(default_factory=list, max_length=400)
    screenshot: ScreenshotInfo | None = None
    app: ForegroundApp | None = None
    history: list[Turn] = Field(default_factory=list)
    response_length: Literal["brief", "detailed"] = "brief"
    language: str = Field(default="en", max_length=16)
    voice_enabled: bool = True
    voice_id: str | None = Field(default=None, max_length=64)
    text: str | None = Field(default=None, max_length=2000)  # typed question (no audio)

    @field_validator("history")
    @classmethod
    def last_ten_turns(cls, v: list[Turn]) -> list[Turn]:
        return v[-20:]  # 10 exchanges = 20 messages


class ElementTarget(BaseModel):
    element_id: str


class PointTarget(BaseModel):
    x: float
    y: float


class TalkResponse(BaseModel):
    """The strict JSON the talk prompt asks the model for."""

    speech: str
    target: ElementTarget | PointTarget | None = None
    action_hint: ActionHint | None = None
