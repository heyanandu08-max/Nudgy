"""Public legal pages and the unsubscribe link in invite emails."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import EmailOptOut
from app.services import auth, legal
from app.services.pages import page

router = APIRouter()


def _legal_page(name: str, settings: Settings) -> HTMLResponse:
    return HTMLResponse(
        page(f"{legal.PAGES[name]} · Nudgy", legal.render(name, settings), settings)
    )


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
def privacy(settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _legal_page("privacy", settings)


@router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
def terms(settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _legal_page("terms", settings)


@router.get("/cookies", response_class=HTMLResponse, include_in_schema=False)
def cookies(settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _legal_page("cookies", settings)


@router.get("/delete-account", response_class=HTMLResponse, include_in_schema=False)
def delete_account(settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _legal_page("delete-account", settings)


@router.get("/licenses", response_class=HTMLResponse, include_in_schema=False)
def licenses(settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _legal_page("licenses", settings)


@router.get("/v1/legal")
def legal_info(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """What the app shows under Settings → About and next to the sign-in form."""
    base = settings.public_url.rstrip("/")
    return {
        "company": settings.company_name or "Nudgy",
        "address": settings.company_address,
        "contact_email": settings.contact_email,
        "terms_version": legal.TERMS_VERSION,
        "links": {name: f"{base}/{name}" for name in legal.PAGES},
    }


def unsubscribe_link(settings: Settings, email: str) -> str:
    token = auth.issue_unsubscribe(settings, email)
    return f"{settings.public_url.rstrip('/')}/email/unsubscribe?token={token}"


@router.get("/email/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
@router.post("/email/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(
    token: str,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """One click, no sign-in (also the List-Unsubscribe target for mail apps)."""
    try:
        email = auth.check_unsubscribe(settings, token)
    except auth.AuthError as e:
        raise HTTPException(400, {"code": "bad_link", "message": "This link isn't valid."}) from e
    if db.get(EmailOptOut, email) is None:
        db.add(EmailOptOut(email=email))
        db.commit()
    return HTMLResponse(
        page(
            "Unsubscribed · Nudgy",
            "<h1>You're unsubscribed</h1><p>You won't get team invitations from Nudgy at this "
            "address. Sign-in links still arrive when you ask for one.</p>",
            settings,
        )
    )
