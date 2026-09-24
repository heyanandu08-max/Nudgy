"""Text-to-speech over plain HTTP: ElevenLabs (default) and OpenAI TTS (fallback)."""

from __future__ import annotations

import httpx

from app.providers.base import ProviderError
from app.providers.openai_compat_llm import v1_url


def _raise_for(resp: httpx.Response, vendor: str) -> None:
    if resp.status_code == 429:
        raise ProviderError("tts_rate_limited", f"{vendor} rate limited", retryable=True)
    if resp.status_code in (401, 403):
        raise ProviderError("tts_auth", f"{vendor} credentials were rejected")
    if resp.status_code >= 400:
        raise ProviderError(
            "tts_failed", f"{vendor} error {resp.status_code}", retryable=resp.status_code >= 500
        )


class ElevenLabsTTS:
    name = "elevenlabs"
    mime = "audio/mpeg"
    DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"

    def __init__(
        self,
        api_key: str | None,
        model: str = "eleven_flash_v2_5",
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise ProviderError("config", "ELEVENLABS_API_KEY is not set")
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.transport = transport

    async def synthesize(self, text: str, *, voice_id: str | None, language: str) -> bytes:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or self.DEFAULT_VOICE}"
        body = {"text": text, "model_id": self.model, "language_code": language}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as c:
                resp = await c.post(
                    url,
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": self.api_key, "Accept": self.mime},
                    json=body,
                )
        except httpx.HTTPError as e:
            raise ProviderError(
                "tts_unreachable", "Could not reach ElevenLabs", retryable=True
            ) from e
        _raise_for(resp, "ElevenLabs")
        return resp.content


class OpenAITTS:
    name = "openai_tts"
    mime = "audio/mpeg"
    URL = "https://api.openai.com/v1/audio/speech"

    def __init__(
        self,
        api_key: str | None,
        model: str = "gpt-4o-mini-tts",
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        base_url: str | None = None,
        default_voice: str | None = "alloy",
    ):
        """`base_url` points it at an OpenAI-compatible gateway (e.g. Deepgram Aura through
        it). Gateways often choose the voice from the model, so `default_voice` may be None:
        then no voice is sent unless the user picked one."""
        if not api_key:
            raise ProviderError(
                "config",
                "NUDGY_GATEWAY_KEY is not set" if base_url else "OPENAI_API_KEY is not set",
            )
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.transport = transport
        self.url = v1_url(base_url, "/audio/speech") if base_url else self.URL
        self.vendor = "the AI gateway" if base_url else "OpenAI"
        self.default_voice = default_voice
        self.gateway = base_url is not None

    async def synthesize(self, text: str, *, voice_id: str | None, language: str) -> bytes:
        body: dict = {"model": self.model, "input": text}
        if voice := voice_id or self.default_voice:
            body["voice"] = voice
        if not self.gateway:
            body["response_format"] = "mp3"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as c:
                resp = await c.post(
                    self.url, headers={"Authorization": f"Bearer {self.api_key}"}, json=body
                )
        except httpx.HTTPError as e:
            raise ProviderError(
                "tts_unreachable", f"Could not reach {self.vendor}", retryable=True
            ) from e
        _raise_for(resp, self.vendor)
        # Gateways may pick the format (mp3 for Aura); tell the player what arrived.
        kind = resp.headers.get("content-type", "").split(";")[0].strip()
        if kind.startswith("audio/"):
            self.mime = kind
        return resp.content
