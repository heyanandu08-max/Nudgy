"""Builds providers from settings. Swap vendors with env vars, not code."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.base import LLMProvider, ProviderError, STTProvider, TTSProvider


@dataclass
class Providers:
    llm: LLMProvider
    stt: STTProvider
    tts: TTSProvider


def build_llm(s: Settings) -> LLMProvider:
    match s.llm_provider:
        case "anthropic":
            from app.providers.anthropic_llm import AnthropicLLM

            return AnthropicLLM(
                s.anthropic_api_key,
                s.llm_model,
                thinking=s.llm_thinking,
                effort=s.llm_effort or None,
            )
        case "fake":
            from app.providers.fake import FakeLLM

            return FakeLLM()
    raise ProviderError("config", f"unknown LLM provider {s.llm_provider!r}")


def build_stt(s: Settings) -> STTProvider:
    match s.stt_provider:
        case "deepgram":
            from app.providers.http_stt import DeepgramSTT

            return DeepgramSTT(s.deepgram_api_key)
        case "openai_whisper":
            from app.providers.http_stt import OpenAIWhisperSTT

            return OpenAIWhisperSTT(s.openai_api_key)
        case "fake":
            from app.providers.fake import FakeSTT

            return FakeSTT()
    raise ProviderError("config", f"unknown STT provider {s.stt_provider!r}")


def build_tts(s: Settings) -> TTSProvider:
    match s.tts_provider:
        case "elevenlabs":
            from app.providers.http_tts import ElevenLabsTTS

            return ElevenLabsTTS(s.elevenlabs_api_key)
        case "openai_tts":
            from app.providers.http_tts import OpenAITTS

            return OpenAITTS(s.openai_api_key)
        case "fake":
            from app.providers.fake import FakeTTS

            return FakeTTS()
    raise ProviderError("config", f"unknown TTS provider {s.tts_provider!r}")


@lru_cache
def _cached() -> Providers:
    s = get_settings()
    return Providers(llm=build_llm(s), stt=build_stt(s), tts=build_tts(s))


def get_providers() -> Providers:
    """FastAPI dependency; tests override it with fakes."""
    return _cached()
