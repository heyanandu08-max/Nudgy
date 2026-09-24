"""Text-to-speech over plain HTTP: ElevenLabs (default) and OpenAI TTS (fallback)."""

from __future__ import annotations

import httpx

from app.providers.base import ProviderError


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
    ):
        if not api_key:
            raise ProviderError("config", "OPENAI_API_KEY is not set")
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.transport = transport

    async def synthesize(self, text: str, *, voice_id: str | None, language: str) -> bytes:
        body = {
            "model": self.model,
            "voice": voice_id or "alloy",
            "input": text,
            "response_format": "mp3",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as c:
                resp = await c.post(
                    self.URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=body
                )
        except httpx.HTTPError as e:
            raise ProviderError("tts_unreachable", "Could not reach OpenAI", retryable=True) from e
        _raise_for(resp, "OpenAI")
        return resp.content
