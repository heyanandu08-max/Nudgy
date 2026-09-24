import time
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user, metered
from app.models import SharedWalkthrough, UsageEvent, User
from app.providers.base import ProviderError, Usage
from app.providers.registry import Providers, get_providers
from app.routers.ask import MAX_AUDIO, _read
from app.schemas.walkthrough import (
    CleanedWalkthrough,
    CleanRequest,
    ShareRequest,
    ShareResponse,
    Walkthrough,
)
from app.services import walkthroughs as svc
from app.services.pages import page
from app.services.usage import finish, record, wav_ms

router = APIRouter()


@router.post("/v1/walkthroughs/clean", response_model=CleanedWalkthrough)
async def clean(
    req: CleanRequest,
    providers: Annotated[Providers, Depends(get_providers)],
    event: Annotated[UsageEvent | None, Depends(metered("lesson_calls"))],
):
    usage, started = Usage(), time.perf_counter()
    try:
        result = await svc.clean(req, providers, usage)
        if event is not None:
            ms = int((time.perf_counter() - started) * 1000)
            finish(event.id, usage.input_tokens, usage.output_tokens, ms)
        return result
    except ProviderError as e:
        # The recording is the author's work: never lose it to an LLM outage.
        if e.code == "config":
            raise HTTPException(502, {"code": e.code, "message": str(e)}) from e
        return svc.fallback_clean(req)


@router.post("/v1/walkthroughs", response_model=ShareResponse)
def share(
    req: ShareRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User | None, Depends(current_user)],
) -> ShareResponse:
    doc = req.walkthrough if req.include_screenshots else req.walkthrough.without_screenshots()
    team_id = None
    if req.team:
        if user is None or user.team_id is None:
            raise HTTPException(
                403, {"code": "no_team", "message": "Sharing to a team needs the Team plan."}
            )
        team_id = user.team_id
    row = SharedWalkthrough(
        slug=svc.new_slug(),
        title=doc.title,
        app=doc.app,
        document=doc.model_dump_json(),
        owner_id=user.id if user else None,
        team_id=team_id,
    )
    db.add(row)
    db.commit()
    return ShareResponse(slug=row.slug, url=f"{settings.public_url.rstrip('/')}/w/{row.slug}")


def _load(db: Session, slug: str) -> SharedWalkthrough:
    row = db.scalar(select(SharedWalkthrough).where(SharedWalkthrough.slug == slug))
    if row is None:
        raise HTTPException(404, {"code": "not_found", "message": "No walkthrough at this link."})
    return row


@router.get("/v1/walkthroughs/{slug}", response_model=Walkthrough)
def fetch(slug: str, db: Annotated[Session, Depends(get_db)]) -> Walkthrough:
    row = _load(db, slug)
    row.views += 1
    db.commit()
    return Walkthrough.model_validate_json(row.document)


@router.get("/w/{slug}", response_class=HTMLResponse, include_in_schema=False)
def share_page(slug: str, db: Annotated[Session, Depends(get_db)]) -> HTMLResponse:
    """Public landing page for a shared link: what it teaches + 'Open in Nudgy'."""
    doc = Walkthrough.model_validate_json(_load(db, slug).document)
    steps = "".join(f"<li>{escape(s.instruction)}</li>" for s in doc.steps)
    title = escape(doc.title)
    html = page(
        f"{doc.title} · Nudgy",
        f"""<h1>{title}</h1><p class="meta">{escape(doc.app)} · {len(doc.steps)} steps</p>
<p>{escape(doc.summary)}</p>
<p><a class="btn" href="nudgy://w/{escape(slug)}">Open in Nudgy</a></p>
<p class="meta">Nudgy guides you through it step by step, in your own copy of the app.</p>
<ol>{steps}</ol>""",
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.post("/v1/transcribe")
async def transcribe(
    providers: Annotated[Providers, Depends(get_providers)],
    user: Annotated[User | None, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    audio: Annotated[UploadFile, File()],
    language: str = "en",
) -> dict:
    data = await _read(audio, MAX_AUDIO, "audio")
    if not data:
        return {"text": ""}
    if user is not None:
        record(db, user, "transcribe", audio_ms=wav_ms(data))
    try:
        text = await providers.stt.transcribe(
            data, mime=audio.content_type or "audio/wav", language=language
        )
    except ProviderError as e:
        raise HTTPException(503 if e.retryable else 502, {"code": e.code, "message": str(e)}) from e
    return {"text": text}
