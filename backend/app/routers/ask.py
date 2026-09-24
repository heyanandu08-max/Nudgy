from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.deps import metered
from app.models import UsageEvent
from app.providers.registry import Providers, get_providers
from app.schemas.ask import AskContext
from app.services.ask import AskInput, run_ask
from app.services.usage import finish, wav_ms
from app.sse import sse

router = APIRouter(prefix="/v1")

MAX_AUDIO = 10 * 1024 * 1024
MAX_SCREENSHOT = 5 * 1024 * 1024


async def _read(upload: UploadFile | None, limit: int, what: str) -> bytes | None:
    if upload is None:
        return None
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{what} too large")
    return data or None


@router.post("/ask")
async def ask(
    providers: Annotated[Providers, Depends(get_providers)],
    usage: Annotated[UsageEvent | None, Depends(metered("asks"))],
    context: Annotated[str, Form()],
    audio: Annotated[UploadFile | None, File()] = None,
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> StreamingResponse:
    try:
        ctx = AskContext.model_validate_json(context)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_input=False)) from e
    inp = AskInput(
        context=ctx,
        audio=await _read(audio, MAX_AUDIO, "audio"),
        audio_mime=(audio.content_type if audio else None) or "audio/wav",
        screenshot=await _read(screenshot, MAX_SCREENSHOT, "screenshot"),
        screenshot_mime=(screenshot.content_type if screenshot else None) or "image/jpeg",
    )

    usage_id = usage.id if usage else None
    audio_ms = wav_ms(inp.audio)

    async def stream():
        async for event, data in run_ask(inp, providers):
            if event == "done" and usage_id is not None:
                u, t = data.get("usage", {}), data.get("timings", {})
                finish(
                    usage_id,
                    u.get("input_tokens", 0),
                    u.get("output_tokens", 0),
                    t.get("total_ms", 0),
                    audio_ms=audio_ms,
                    tts_chars=len(data.get("speech", "")) if ctx.voice_enabled else 0,
                )
            yield sse(event, data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
