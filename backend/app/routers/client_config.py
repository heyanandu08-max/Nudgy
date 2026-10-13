from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings, load_yaml
from app.schemas.config import ClientConfig, Language, Voice

router = APIRouter(prefix="/v1")


@router.get("/config", response_model=ClientConfig)
def client_config(settings: Annotated[Settings, Depends(get_settings)]) -> ClientConfig:
    """Options the desktop app shows in Settings (driven by config files, not code)."""
    languages = [Language(**lang) for lang in load_yaml("languages.yaml")["languages"]]
    voices = [Voice(**v) for v in load_yaml("voices.yaml").get(settings.tts_provider, [])]
    return ClientConfig(languages=languages, voices=voices, tts_provider=settings.tts_provider)
