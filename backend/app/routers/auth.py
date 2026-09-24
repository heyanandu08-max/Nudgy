"""Sign-in: email magic link, Google, Apple. Each ends by handing a session token to the
desktop app through the nudgy:// deep link."""

from html import escape
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import signed_in
from app.models import Team, User
from app.services import account_data, auth
from app.services.email import EmailSender, get_email_sender
from app.services.pages import page
from app.services.stripe_api import StripeClient, StripeError
from app.services.usage import summary

router = APIRouter()


def get_mailer(settings: Annotated[Settings, Depends(get_settings)]) -> EmailSender:
    return get_email_sender(settings)


def get_google(settings: Annotated[Settings, Depends(get_settings)]) -> auth.IdTokenVerifier:
    return auth.google_verifier(settings)


def get_apple(settings: Annotated[Settings, Depends(get_settings)]) -> auth.IdTokenVerifier:
    return auth.apple_verifier(settings)


def get_oauth_http() -> httpx.Client:
    return httpx.Client(timeout=15)


def _handoff(token: str, email: str) -> HTMLResponse:
    """Page shown in the browser after sign-in; it opens the app with the session token."""
    link = "nudgy://auth?" + urlencode({"token": token})
    html = page(
        "Signed in · Nudgy",
        f"""<h1>You're signed in</h1><p>Signed in as {escape(email)}. Nudgy should open by itself.</p>
<p><a class="btn" href="{escape(link)}">Open Nudgy</a></p><p class="meta">You can close this tab.</p>
<script>location.href = {link!r};</script>""",
    )
    return HTMLResponse(
        html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    )


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><title>Nudgy</title><p style='font:16px system-ui;margin:60px auto;max-width:520px'>"
        f"{escape(message)}</p>",
        status_code=status,
    )


def _sign_in(db: Session, settings: Settings, email: str, name: str = "") -> HTMLResponse:
    user = auth.get_or_create_user(db, email, name)
    return _handoff(auth.issue_session(settings, user), user.email)


# --- magic link ---


class MagicRequest(BaseModel):
    email: EmailStr


@router.post("/v1/auth/magic")
def send_magic_link(
    req: MagicRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    mailer: Annotated[EmailSender, Depends(get_mailer)],
) -> dict:
    token = auth.issue_magic(settings, req.email.lower())
    link = f"{settings.public_url.rstrip('/')}/auth/magic?{urlencode({'token': token})}"
    mailer.send(
        req.email,
        "Your Nudgy sign-in link",
        f"Click to sign in to Nudgy:\n\n{link}\n\nThe link works once and expires in 15 minutes. "
        "If you didn't ask for it, you can ignore this email.",
    )
    return {"sent": True}


@router.get("/auth/magic", response_class=HTMLResponse, include_in_schema=False)
def redeem_magic_link(
    token: str,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    try:
        email = auth.redeem_magic(settings, db, token)
    except auth.AuthError as e:
        msg = {
            "expired": "This sign-in link has expired.",
            "used": "This sign-in link was already used.",
        }
        return _error_page(
            msg.get(str(e), "This sign-in link isn't valid.") + " Request a new one from Nudgy."
        )
    return _sign_in(db, settings, email)


# --- Google ---


@router.get("/v1/auth/google/start", include_in_schema=False)
def google_start(settings: Annotated[Settings, Depends(get_settings)]) -> RedirectResponse:
    if not settings.google_client_id:
        raise HTTPException(503, {"code": "config", "message": "Google sign-in is not configured"})
    q = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.public_url.rstrip('/')}/v1/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": auth.issue_state(settings, "google"),
        "prompt": "select_account",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(q))


@router.get("/v1/auth/google/callback", response_class=HTMLResponse, include_in_schema=False)
def google_callback(
    code: str,
    state: str,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    verifier: Annotated[auth.IdTokenVerifier, Depends(get_google)],
    http: Annotated[httpx.Client, Depends(get_oauth_http)],
) -> HTMLResponse:
    try:
        auth.check_state(settings, state, "google")
        r = http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": f"{settings.public_url.rstrip('/')}/v1/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        if r.status_code != 200 or "id_token" not in r.json():
            raise auth.AuthError("token exchange failed")
        who = verifier.verify(r.json()["id_token"])
    except (auth.AuthError, httpx.HTTPError):
        return _error_page("Google sign-in didn't work. Please try again.")
    return _sign_in(db, settings, who.email, who.name)


# --- Apple ---


@router.get("/v1/auth/apple/start", include_in_schema=False)
def apple_start(settings: Annotated[Settings, Depends(get_settings)]) -> RedirectResponse:
    if not settings.apple_client_id:
        raise HTTPException(503, {"code": "config", "message": "Apple sign-in is not configured"})
    q = {
        "client_id": settings.apple_client_id,
        "redirect_uri": f"{settings.public_url.rstrip('/')}/v1/auth/apple/callback",
        "response_type": "code id_token",
        "response_mode": "form_post",
        "scope": "name email",
        "state": auth.issue_state(settings, "apple"),
    }
    return RedirectResponse("https://appleid.apple.com/auth/authorize?" + urlencode(q))


@router.post("/v1/auth/apple/callback", response_class=HTMLResponse, include_in_schema=False)
def apple_callback(
    state: Annotated[str, Form()],
    id_token: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    verifier: Annotated[auth.IdTokenVerifier, Depends(get_apple)],
) -> HTMLResponse:
    # The id_token posted by Apple is signed by Apple and bound to our client id — enough to
    # identify the user; we don't need Apple's refresh tokens.
    try:
        auth.check_state(settings, state, "apple")
        who = verifier.verify(id_token)
    except auth.AuthError:
        return _error_page("Apple sign-in didn't work. Please try again.")
    return _sign_in(db, settings, who.email, who.name)


# --- me ---


@router.get("/v1/me")
def me(user: Annotated[User, Depends(signed_in)], db: Annotated[Session, Depends(get_db)]) -> dict:
    team = db.get(Team, user.team_id) if user.team_id else None
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "subscription_status": user.subscription_status,
        "team": {
            "id": team.id,
            "name": team.name,
            "seats": team.seats,
            "owner": team.owner_id == user.id,
        }
        if team
        else None,
        **summary(db, user),
    }


@router.get("/v1/me/export")
def export_me(
    user: Annotated[User, Depends(signed_in)], db: Annotated[Session, Depends(get_db)]
) -> dict:
    """Everything the server stores about you, as JSON."""
    return account_data.export(db, user)


def optional_stripe(settings: Annotated[Settings, Depends(get_settings)]) -> StripeClient | None:
    try:
        return StripeClient(settings.stripe_secret_key)
    except StripeError:
        return None


@router.delete("/v1/me")
def delete_me(
    user: Annotated[User, Depends(signed_in)],
    db: Annotated[Session, Depends(get_db)],
    stripe: Annotated[StripeClient | None, Depends(optional_stripe)],
) -> dict:
    """Deletes the account and all server-side data. A running subscription is cancelled first;
    if that fails nothing is deleted, so nobody keeps paying for an account that is gone."""
    if user.stripe_subscription_id and user.subscription_status not in (None, "canceled"):
        if stripe is None:
            raise HTTPException(503, {"code": "config", "message": "Billing is not configured."})
        try:
            stripe.cancel_subscription(user.stripe_subscription_id)
        except StripeError as e:
            raise HTTPException(502, {"code": "billing_error", "message": str(e)}) from e
    return {"deleted": True, **account_data.delete_user(db, user)}


@router.post("/v1/auth/refresh")
def refresh(
    user: Annotated[User, Depends(signed_in)], settings: Annotated[Settings, Depends(get_settings)]
) -> dict:
    """Swaps a still-valid session for a fresh one (the app calls this on start)."""
    return {"token": auth.issue_session(settings, user)}
