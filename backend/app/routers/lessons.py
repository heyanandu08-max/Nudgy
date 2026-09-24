"""Tutor mode endpoints. JSON in/out (not streamed): plans and verdicts are small."""

from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError

from app.deps import current_user, metered
from app.models import UsageEvent, User
from app.providers.base import ProviderError, Usage
from app.providers.registry import Providers, get_providers
from app.routers.ask import MAX_SCREENSHOT, _read
from app.schemas.lessons import (
    LessonPlan,
    LocateContext,
    PlanContext,
    SpeakRequest,
    VerifyContext,
    VerifyResult,
)
from app.services import lessons

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


@router.post("/lessons/plan", response_model=LessonPlan)
async def plan(
    providers: Annotated[Providers, Depends(get_providers)],
    _usage: Annotated[UsageEvent | None, Depends(metered("lessons"))],
    context: Annotated[str, Form()],
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> LessonPlan:
    ctx = _context(context, PlanContext)
    try:
        return await lessons.plan_lesson(
            ctx, await _read(screenshot, MAX_SCREENSHOT, "screenshot"), providers, Usage()
        )
    except ProviderError as e:
        raise _provider_error(e) from e


@router.post("/lessons/verify", response_model=VerifyResult)
async def verify(
    providers: Annotated[Providers, Depends(get_providers)],
    _usage: Annotated[UsageEvent | None, Depends(metered("lesson_calls"))],
    context: Annotated[str, Form()],
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> VerifyResult:
    ctx = _context(context, VerifyContext)
    try:
        return await lessons.verify_step(
            ctx, await _read(screenshot, MAX_SCREENSHOT, "screenshot"), providers, Usage()
        )
    except ProviderError as e:
        raise _provider_error(e) from e


@router.post("/lessons/locate")
async def locate(
    providers: Annotated[Providers, Depends(get_providers)],
    _usage: Annotated[UsageEvent | None, Depends(metered("lesson_calls"))],
    context: Annotated[str, Form()],
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> dict:
    ctx = _context(context, LocateContext)
    try:
        target = await lessons.locate(
            ctx, await _read(screenshot, MAX_SCREENSHOT, "screenshot"), providers, Usage()
        )
    except ProviderError as e:
        raise _provider_error(e) from e
    return {"target": target}


@router.post("/speak")
async def speak(
    req: SpeakRequest,
    providers: Annotated[Providers, Depends(get_providers)],
    _user: Annotated[User | None, Depends(current_user)],
) -> dict:
    try:
        clips = await lessons.speak(req.text, providers.tts, req.voice_id, req.language)
    except ProviderError as e:
        raise _provider_error(e) from e
    return {"clips": clips}
