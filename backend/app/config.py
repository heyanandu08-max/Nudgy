from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BACKEND_DIR / "config"
PROMPTS_DIR = BACKEND_DIR / "prompts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NUDGY_",
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    env: str = "dev"
    database_url: str = "sqlite:///./nudgy.db"
    cors_origins: str = "http://localhost:1420,tauri://localhost,http://tauri.localhost"
    jwt_secret: str = "change-me"

    llm_provider: str = "fake"
    stt_provider: str = "fake"
    tts_provider: str = "fake"
    llm_model: str = "claude-sonnet-5"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
