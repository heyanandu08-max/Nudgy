"""Tutor mode endpoints. JSON in/out (not streamed): plans and verdicts are small."""

import time
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user, get_clock, metered
from app.models import UsageEvent, User
from app.providers.base import ProviderError, Usage
from app.providers.registry import Providers, get_providers
from app.routers.ask import MAX_SCREENSHOT, _read
from app.schemas.lessons import (
    LocateContext,
    PlanContext,
    PlannedLesson,
    SpeakRequest,
    VerifyContext,
    VerifyResult,
)
from app.services import access, lessons
from app.services.usage import finish, record, refund

router = APIRouter(prefix="/v1")

M = TypeVar("M", bound=BaseModel)


def _context(raw: str, model: type[M]) -> M:
    try:
        return model.model_validate_json(raw)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_input=False)) from e


def _provider_error(e: ProviderError) -> HTTPException:
    status = 503 if e.retryable else 502
    return HTTPException(status, {"code": e.code, "message": str(e)})


def _log(event: UsageEvent | None, usage: Usage, started: float) -> None:
    if event is not None:
        latency = int((time.perf_counter() - started) * 1000)
        finish(event.id, usage.input_tokens, usage.output_tokens, latency)


@router.post("/lessons/plan", response_model=PlannedLesson)
async def plan(
    providers: Annotated[Providers, Depends(get_providers)],
    event: Annotated[UsageEvent | None, Depends(metered("lessons"))],
    user: Annotated[User | None, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    context: Annotated[str, Form()],
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> PlannedLesson:
    ctx = _context(context, PlanContext)
    usage, started = Usage(), time.perf_counter()
    try:
        result = await lessons.plan_lesson(
            ctx, await _read(screenshot, MAX_SCREENSHOT, "screenshot"), providers, usage
        )
    except ProviderError as e:
        refund(db, event)  # no plan, no lesson: it doesn't count against the month
        raise _provider_error(e) from e
    _log(event, usage, started)
    quota = access.lesson_quota(db, settings, user, clock())
    return PlannedLesson(**result.model_dump(), quota=quota.as_dict() if quota else None)


@router.post("/lessons/verify", response_model=VerifyResult)
async def verify(
    providers: Annotated[Providers, Depends(get_providers)],
    event: Annotated[UsageEvent | None, Depends(metered("lesson_calls"))],
    context: Annotated[str, Form()],
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> VerifyResult:
    ctx = _context(context, VerifyContext)
    usage, started = Usage(), time.perf_counter()
    try:
        result = await lessons.verify_step(
            ctx, await _read(screenshot, MAX_SCREENSHOT, "screenshot"), providers, usage
        )
    except ProviderError as e:
        raise _provider_error(e) from e
    _log(event, usage, started)
    return result


@router.post("/lessons/locate")
async def locate(
    providers: Annotated[Providers, Depends(get_providers)],
    event: Annotated[UsageEvent | None, Depends(metered("lesson_calls"))],
    context: Annotated[str, Form()],
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> dict:
    ctx = _context(context, LocateContext)
    usage, started = Usage(), time.perf_counter()
    try:
        target = await lessons.locate(
            ctx, await _read(screenshot, MAX_SCREENSHOT, "screenshot"), providers, usage
        )
    except ProviderError as e:
        raise _provider_error(e) from e
    _log(event, usage, started)
    return {"target": target}


@router.post("/speak")
async def speak(
    req: SpeakRequest,
    providers: Annotated[Providers, Depends(get_providers)],
    user: Annotated[User | None, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        clips = await lessons.speak(req.text, providers.tts, req.voice_id, req.language)
    except ProviderError as e:
        raise _provider_error(e) from e
    if user is not None:
        record(db, user, "speak", tts_chars=len(req.text))
    return {"clips": clips}
