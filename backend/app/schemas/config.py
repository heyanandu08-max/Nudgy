from pydantic import BaseModel


class Language(BaseModel):
    code: str
    name: str
    default: bool = False


class Voice(BaseModel):
    id: str
    name: str


class ClientConfig(BaseModel):
    languages: list[Language]
    voices: list[Voice]
    tts_provider: str
