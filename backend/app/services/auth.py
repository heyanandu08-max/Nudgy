"""Sessions and sign-in: magic links, Google and Apple (OIDC id_token), JWT sessions."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Protocol

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Team, TeamInvite, UsedToken, User

ALG = "HS256"
MAGIC_TTL = 15 * 60
STATE_TTL = 10 * 60


class AuthError(Exception):
    pass


def _encode(s: Settings, claims: dict, ttl: int) -> str:
    now = int(time.time())
    return jwt.encode({**claims, "iat": now, "exp": now + ttl}, s.jwt_secret, algorithm=ALG)


def _decode(s: Settings, token: str, purpose: str) -> dict:
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=[ALG])
    except jwt.ExpiredSignatureError as e:
        raise AuthError("expired") from e
    except jwt.PyJWTError as e:
        raise AuthError("invalid") from e
    if claims.get("purpose") != purpose:
        raise AuthError("invalid")
    return claims


# --- sessions ---


def issue_session(s: Settings, user: User) -> str:
    return _encode(
        s, {"purpose": "session", "sub": str(user.id), "email": user.email}, s.session_days * 86400
    )


def user_id_from_session(s: Settings, token: str) -> int:
    return int(_decode(s, token, "session")["sub"])


# --- magic links ---


def issue_magic(s: Settings, email: str) -> str:
    return _encode(s, {"purpose": "magic", "email": email, "jti": secrets.token_hex(16)}, MAGIC_TTL)


def redeem_magic(s: Settings, db: Session, token: str) -> str:
    """Returns the email; each link works once."""
    claims = _decode(s, token, "magic")
    if db.get(UsedToken, claims["jti"]) is not None:
        raise AuthError("used")
    db.add(UsedToken(jti=claims["jti"]))
    db.flush()
    return claims["email"]


# --- OAuth state (CSRF) ---


def issue_state(s: Settings, provider: str) -> str:
    return _encode(
        s,
        {"purpose": "oauth_state", "provider": provider, "nonce": secrets.token_hex(8)},
        STATE_TTL,
    )


def check_state(s: Settings, state: str, provider: str) -> None:
    if _decode(s, state, "oauth_state").get("provider") != provider:
        raise AuthError("invalid")


# --- id_token verification (Google / Apple) ---


@dataclass
class Identity:
    email: str
    name: str = ""


class IdTokenVerifier(Protocol):
    def verify(self, id_token: str) -> Identity: ...


class JwksVerifier:
    """Verifies an OIDC id_token against the provider's published signing keys."""

    def __init__(self, jwks_url: str, issuers: list[str], audience: str):
        self.client = jwt.PyJWKClient(jwks_url, cache_keys=True)
        self.issuers, self.audience = issuers, audience

    def verify(self, id_token: str) -> Identity:
        try:
            key = self.client.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token, key.key, algorithms=["RS256", "ES256"], audience=self.audience
            )
        except jwt.PyJWTError as e:
            raise AuthError("invalid id_token") from e
        if claims.get("iss") not in self.issuers:
            raise AuthError("wrong issuer")
        if claims.get("email_verified") in (False, "false"):
            raise AuthError("email not verified")
        email = claims.get("email")
        if not email:
            raise AuthError("no email in id_token")
        return Identity(email=email.lower(), name=claims.get("name", ""))


def google_verifier(s: Settings) -> IdTokenVerifier:
    return JwksVerifier(
        "https://www.googleapis.com/oauth2/v3/certs",
        ["https://accounts.google.com", "accounts.google.com"],
        s.google_client_id,
    )


def apple_verifier(s: Settings) -> IdTokenVerifier:
    return JwksVerifier(
        "https://appleid.apple.com/auth/keys", ["https://appleid.apple.com"], s.apple_client_id
    )


def apple_client_secret(s: Settings) -> str:
    """Apple requires a short-lived ES256 JWT, signed with the team's key, as client_secret."""
    now = int(time.time())
    return jwt.encode(
        {
            "iss": s.apple_team_id,
            "iat": now,
            "exp": now + 300,
            "aud": "https://appleid.apple.com",
            "sub": s.apple_client_id,
        },
        s.apple_private_key,
        algorithm="ES256",
        headers={"kid": s.apple_key_id},
    )


# --- users ---


def get_or_create_user(db: Session, email: str, name: str = "") -> User:
    email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name)
        db.add(user)
        db.flush()
    elif name and not user.name:
        user.name = name
    # Accept a pending team invite on first sign-in with that address.
    if user.team_id is None:
        invite = db.scalar(select(TeamInvite).where(TeamInvite.email == email))
        if invite is not None and db.get(Team, invite.team_id) is not None:
            user.team_id = invite.team_id
            user.plan = "team"
            db.delete(invite)
    db.commit()
    return user
