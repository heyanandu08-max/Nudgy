"""Any OpenAI-compatible chat endpoint (`/v1/chat/completions`): local gateways, free-model
routers, self-hosted models. Streamed over SSE with plain httpx.

Set NUDGY_LLM_PROVIDER=openai_compatible, NUDGY_GATEWAY_URL, NUDGY_GATEWAY_KEY and
NUDGY_LLM_MODEL (one of the names the service lists at GET <gateway>/v1/models). If its models
can't read images, set NUDGY_LLM_VISION=false: Nudgy then sends only the UI element list,
which is still enough to point at named buttons. The same gateway can also do speech-to-text
and the voice (see http_stt.py / http_tts.py).
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator

import httpx

from app.providers.base import AudioPart, ImagePart, Message, ProviderError, Usage


def v1_url(base_url: str, path: str) -> str:
    """Joins an OpenAI-compatible base URL and an endpoint path. A bare host
    (`http://127.0.0.1:31415`) gets `/v1`; a base that already has a path
    (`…/v1`, `…/api/v1`, `…/v1beta/openai`) is used as given."""
    base = base_url.rstrip("/")
    has_path = "/" in base.split("://", 1)[-1]
    return f"{base}{path}" if has_path else f"{base}/v1{path}"


def to_openai(system: str, messages: list[Message], vision: bool) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        texts = [p for p in m.parts if isinstance(p, str)]
        images = [p for p in m.parts if isinstance(p, ImagePart)] if vision else []
        audio = [p for p in m.parts if isinstance(p, AudioPart)]
        if not images and not audio:
            out.append({"role": m.role, "content": "\n\n".join(texts)})
            continue
        content: list[dict] = [{"type": "text", "text": t} for t in texts]
        for img in images:
            data = base64.standard_b64encode(img.data).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{img.media_type};base64,{data}"}}
            )
        for clip in audio:
            data = base64.standard_b64encode(clip.data).decode("ascii")
            content.append(
                {"type": "input_audio", "input_audio": {"data": data, "format": clip.format}}
            )
        out.append({"role": m.role, "content": content})
    return out


TRANSCRIBE_PROMPT = (
    "Transcribe the recording exactly, in {language}. Reply with only the words spoken, "
    "no quotes or notes. If nobody speaks, reply with nothing."
)


class ChatAudioSTT:
    """Speech-to-text by sending the recording to a chat model that can listen (e.g. Gemini
    through its OpenAI-compatible endpoint). Shares the LLM's service, retries and fallback,
    so one free key covers both."""

    name = "chat_audio"

    def __init__(self, llm: OpenAICompatibleLLM):
        self.llm = llm

    async def transcribe(self, audio: bytes, *, mime: str, language: str) -> str:
        fmt = "mp3" if "mpeg" in mime or "mp3" in mime else "wav"
        text = ""
        try:
            async for delta in self.llm.stream(
                system=TRANSCRIBE_PROMPT.format(language=language),
                messages=[Message("user", [AudioPart(audio, fmt)])],
                max_tokens=400,
                usage=Usage(),
            ):
                text += delta
        except ProviderError as e:
            raise ProviderError(
                e.code.replace("llm_", "stt_", 1), str(e), retryable=e.retryable
            ) from e
        return text.strip().strip('"').strip()


def _error(status: int) -> ProviderError:
    if status in (401, 403):
        return ProviderError("llm_auth", "LLM credentials were rejected")
    if status == 429:
        return ProviderError("llm_rate_limited", "LLM rate limited", retryable=True)
    return ProviderError("llm_failed", f"LLM error {status}", retryable=status >= 500)


class OpenAICompatibleLLM:
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        model: str,
        *,
        vision: bool = True,
        fallback_model: str | None = None,
        retry_delay: float = 1.0,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not base_url:
            raise ProviderError("config", "NUDGY_GATEWAY_URL is not set")
        self.url = v1_url(base_url, "/chat/completions")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self.fallback_model = fallback_model or None
        self.retry_delay = retry_delay
        self.vision = vision
        self.timeout = timeout
        self.transport = transport

    async def stream(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int,
        usage: Usage,
        effort: str | None = None,  # no portable equivalent; ignored
    ) -> AsyncIterator[str]:
        """Free and shared models are often briefly overloaded (429/503). Before anything has
        been said: retry once, then try the fallback model. Mid-answer failures aren't retried
        (the words already went to the user)."""
        attempts = [(self.model, 0.0), (self.model, self.retry_delay)]
        if self.fallback_model and self.fallback_model != self.model:
            attempts.append((self.fallback_model, 0.0))
        for i, (model, delay) in enumerate(attempts):
            if delay:
                await asyncio.sleep(delay)
            started = False
            try:
                async for text in self._stream_once(model, system, messages, max_tokens, usage):
                    started = True
                    yield text
                return
            except ProviderError as e:
                if started or not e.retryable or i == len(attempts) - 1:
                    raise

    async def _stream_once(
        self, model: str, system: str, messages: list[Message], max_tokens: int, usage: Usage
    ) -> AsyncIterator[str]:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": to_openai(system, messages, self.vision),
        }
        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client,
                client.stream("POST", self.url, headers=self.headers, json=body) as resp,
            ):
                if resp.status_code >= 400:
                    await resp.aread()
                    raise _error(resp.status_code)
                # Some gateways ignore "stream" and answer with one JSON body.
                if "text/event-stream" not in resp.headers.get("content-type", ""):
                    data = json.loads(await resp.aread())
                    self._usage(data, usage)
                    choice = (data.get("choices") or [{}])[0]
                    self._check(choice)
                    text = (choice.get("message") or {}).get("content") or ""
                    if text:
                        yield text
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    self._usage(chunk, usage)
                    for choice in chunk.get("choices") or []:
                        self._check(choice)
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield delta
        except httpx.TimeoutException as e:
            raise ProviderError("llm_unreachable", "The LLM timed out", retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError("llm_unreachable", "Could not reach the LLM", retryable=True) from e

    @staticmethod
    def _check(choice: dict) -> None:
        if choice.get("finish_reason") == "content_filter":
            raise ProviderError("llm_refused", "The model declined this request")

    @staticmethod
    def _usage(data: dict, usage: Usage) -> None:
        u = data.get("usage") or {}
        usage.input_tokens += int(u.get("prompt_tokens") or 0)
        usage.output_tokens += int(u.get("completion_tokens") or 0)
