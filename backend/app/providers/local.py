"""Nudgy's built-in AI: free models running on the user's own PC, no API keys.

- LocalLLM: llama.cpp's `llama-server` (OpenAI-compatible chat API) running a vision model
  (Gemma 3 4B by default) with its image projector.
- LocalWhisperSTT: whisper.cpp's `whisper-server` (/inference).
- SystemTTS: no audio from the server; the app speaks with the computer's own voice.

The desktop app downloads the models and starts both servers (app/src-tauri/src/local_ai.rs).
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import httpx

from app.providers.base import ImagePart, Message, ProviderError, Usage


def _to_openai(system: str, messages: list[Message]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        content: list[dict] = []
        for p in m.parts:
            if isinstance(p, ImagePart):
                b64 = base64.standard_b64encode(p.data).decode("ascii")
                content.append(
                    {"type": "image_url", "image_url": {"url": f"data:{p.media_type};base64,{b64}"}}
                )
            else:
                content.append({"type": "text", "text": p})
        out.append({"role": m.role, "content": content})
    return out


class LocalLLM:
    """A llama.cpp server on this machine. Answers are JSON (the prompts ask for it, and the
    server's JSON grammar guarantees it parses)."""

    name = "local"

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def stream(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int,
        usage: Usage,
        effort: str | None = None,
    ) -> AsyncIterator[str]:
        body = {
            "messages": _to_openai(system, messages),
            "max_tokens": min(max_tokens, 1024),
            "temperature": 0.2,
            "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {"type": "json_object"},
            "cache_prompt": True,  # reuse the system prompt across questions: much faster
        }
        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as c,
                c.stream("POST", f"{self.url}/v1/chat/completions", json=body) as resp,
            ):
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode(errors="replace")[:200]
                    raise ProviderError(
                        "llm_failed", f"Built-in AI error {resp.status_code}: {detail}"
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if u := chunk.get("usage"):
                        usage.input_tokens += u.get("prompt_tokens", 0)
                        usage.output_tokens += u.get("completion_tokens", 0)
                    for choice in chunk.get("choices", []):
                        if text := (choice.get("delta") or {}).get("content"):
                            yield text
        except httpx.ConnectError as e:
            raise ProviderError(
                "llm_unreachable",
                "Nudgy's built-in AI isn't running yet. Give it a moment after starting Nudgy.",
                retryable=True,
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError(
                "llm_timeout", "The built-in AI took too long.", retryable=True
            ) from e
        except httpx.HTTPError as e:
            raise ProviderError("llm_failed", f"Built-in AI error: {e}") from e


class LocalWhisperSTT:
    """A whisper.cpp server on this machine (the app sends WAV)."""

    name = "local_whisper"

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def transcribe(self, audio: bytes, *, mime: str, language: str) -> str:
        files = {"file": ("question.wav", audio, mime or "audio/wav")}
        data = {"response_format": "json", "language": language or "auto", "temperature": "0"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as c:
                resp = await c.post(f"{self.url}/inference", files=files, data=data)
        except httpx.HTTPError as e:
            raise ProviderError(
                "stt_unreachable", "The built-in speech engine isn't running", retryable=True
            ) from e
        if resp.status_code >= 400:
            raise ProviderError("stt_failed", f"Built-in speech engine error {resp.status_code}")
        return (resp.json().get("text") or "").strip()


class SystemTTS:
    """No audio from the server: the app reads answers aloud with the computer's own voice."""

    name = "system"
    mime = "none"

    async def synthesize(self, text: str, *, voice_id: str | None, language: str) -> bytes:
        return b""
