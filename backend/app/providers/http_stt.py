"""Speech-to-text over plain HTTP: Deepgram, OpenAI Whisper, and any OpenAI-compatible
gateway (`/v1/audio/transcriptions`)."""

from __future__ import annotations

import httpx

from app.providers.base import ProviderError
from app.providers.openai_compat_llm import v1_url


def _raise_for(resp: httpx.Response, vendor: str) -> None:
    if resp.status_code == 429:
        raise ProviderError("stt_rate_limited", f"{vendor} rate limited", retryable=True)
    if resp.status_code in (401, 403):
        raise ProviderError("stt_auth", f"{vendor} credentials were rejected")
    if resp.status_code >= 400:
        raise ProviderError(
            "stt_failed", f"{vendor} error {resp.status_code}", retryable=resp.status_code >= 500
        )


class DeepgramSTT:
    name = "deepgram"
    URL = "https://api.deepgram.com/v1/listen"

    def __init__(
        self,
        api_key: str | None,
        model: str = "nova-3",
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise ProviderError("config", "DEEPGRAM_API_KEY is not set")
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.transport = transport

    async def transcribe(self, audio: bytes, *, mime: str, language: str) -> str:
        params = {"model": self.model, "language": language, "smart_format": "true"}
        headers = {"Authorization": f"Token {self.api_key}", "Content-Type": mime}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as c:
                resp = await c.post(self.URL, params=params, headers=headers, content=audio)
        except httpx.HTTPError as e:
            raise ProviderError(
                "stt_unreachable", "Could not reach Deepgram", retryable=True
            ) from e
        _raise_for(resp, "Deepgram")
        alts = resp.json()["results"]["channels"][0]["alternatives"]
        return (alts[0].get("transcript") or "").strip() if alts else ""


class OpenAIWhisperSTT:
    name = "openai_whisper"
    URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(
        self,
        api_key: str | None,
        model: str = "whisper-1",
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        base_url: str | None = None,
    ):
        """`base_url` points it at an OpenAI-compatible gateway instead of OpenAI."""
        if not api_key:
            raise ProviderError(
                "config",
                "NUDGY_GATEWAY_KEY is not set" if base_url else "OPENAI_API_KEY is not set",
            )
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.transport = transport
        self.url = v1_url(base_url, "/audio/transcriptions") if base_url else self.URL
        self.vendor = "the AI gateway" if base_url else "OpenAI"

    async def transcribe(self, audio: bytes, *, mime: str, language: str) -> str:
        files = {"file": ("speech.wav", audio, mime)}
        data = {"model": self.model, "language": language, "response_format": "json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as c:
                resp = await c.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=files,
                    data=data,
                )
        except httpx.HTTPError as e:
            raise ProviderError(
                "stt_unreachable", f"Could not reach {self.vendor}", retryable=True
            ) from e
        _raise_for(resp, self.vendor)
        return (resp.json().get("text") or "").strip()
