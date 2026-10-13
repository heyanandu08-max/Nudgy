import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BACKEND_DIR / "config"
PROMPTS_DIR = BACKEND_DIR / "prompts"
# Packaged as one program (nudgy-server.exe): the .env sits next to the program.
FROZEN_ENV = (
    (Path(sys.executable).resolve().parent / ".env",) if getattr(sys, "frozen", False) else ()
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NUDGY_",
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env", *FROZEN_ENV),
        extra="ignore",
    )

    env: str = "dev"
    database_url: str = "sqlite:///./nudgy.db"
    cors_origins: str = "http://localhost:1420,tauri://localhost,http://tauri.localhost"
    jwt_secret: str = "change-me"
    # Public base URL used in share links and auth callbacks (https://nudgy.app in prod).
    public_url: str = "http://127.0.0.1:8787"
    # Require sign-in for AI endpoints (true in production; false keeps local dev key-less).
    auth_required: bool = False
    session_days: int = 30
    # Email for magic links: "console" (logs the link — dev only) or "smtp".
    email_provider: str = "console"
    email_from: str = "Nudgy <hello@nudgy.app>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    apple_client_id: str = ""  # Services ID
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key: str = ""  # contents of the .p8 key (PEM)

    # --- Launch and free access (DECISIONS D38) ---
    # The day Nudgy ships to real users. Everyone has unlimited use until FREE_UNTIL =
    # LAUNCH_DATE + 365 days, the same calendar date for every account. Unset (the dev default)
    # means there is no free window: free accounts are on the capped tier straight away.
    launch_date: date | None = None
    # Pushes FREE_UNTIL to this date instead (the admin API can also set it without a restart).
    free_until_override: date | None = None
    # Only seeds the app_settings row on first start; change the row via the admin API.
    free_tier_lessons_per_month: int = Field(default=5, ge=0)
    # Enables /v1/admin/* (header X-Admin-Token). Unset = admin API off.
    admin_token: str | None = None

    # PayPal subscriptions (developer.paypal.com → Apps & Credentials). Plan IDs: plans.yaml.
    paypal_client_id: str | None = Field(default=None, validation_alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: str | None = Field(default=None, validation_alias="PAYPAL_CLIENT_SECRET")
    paypal_webhook_id: str | None = Field(default=None, validation_alias="PAYPAL_WEBHOOK_ID")
    paypal_env: str = Field(default="sandbox", validation_alias="PAYPAL_ENV")  # sandbox | live

    llm_provider: str = "fake"
    stt_provider: str = "fake"
    tts_provider: str = "fake"
    llm_model: str = "claude-sonnet-5"
    llm_thinking: str = "disabled"  # disabled | adaptive
    llm_effort: str = "low"  # low | medium | high | "" (provider default)

    # Vendor keys use their conventional names (no NUDGY_ prefix).
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    deepgram_api_key: str | None = Field(default=None, validation_alias="DEEPGRAM_API_KEY")
    elevenlabs_api_key: str | None = Field(default=None, validation_alias="ELEVENLABS_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    @field_validator("launch_date", "free_until_override", "admin_token", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        return None if v == "" else v

    def check_production_safety(self) -> None:
        """Refuses to start a non-dev deployment with unsafe defaults."""
        if self.env == "dev":
            return
        problems = []
        if self.jwt_secret == "change-me" or len(self.jwt_secret) < 32:
            problems.append("NUDGY_JWT_SECRET must be a random string of at least 32 characters")
        if not self.auth_required:
            problems.append("NUDGY_AUTH_REQUIRED must be true outside development")
        if self.email_provider == "console":
            problems.append("NUDGY_EMAIL_PROVIDER=console would log sign-in links")
        fakes = [
            name
            for name, value in (
                ("LLM", self.llm_provider),
                ("STT", self.stt_provider),
                ("TTS", self.tts_provider),
            )
            if value == "fake"
        ]
        if fakes:
            problems.append(f"NUDGY_{'/'.join(fakes)}_PROVIDER is 'fake'")
        if self.paypal_client_id and self.paypal_env != "live":
            problems.append("PAYPAL_ENV must be 'live' in production (it is the test sandbox)")
        if self.admin_token is not None and len(self.admin_token) < 32:
            problems.append("NUDGY_ADMIN_TOKEN must be at least 32 characters")
        if not self.public_url.startswith("https://"):
            problems.append("NUDGY_PUBLIC_URL must be the server's https:// address")
        if problems:
            raise RuntimeError("Unsafe configuration: " + "; ".join(problems))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
