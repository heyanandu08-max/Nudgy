"""Any OpenAI-compatible chat endpoint (`/v1/chat/completions`): local gateways, free-model
routers, self-hosted models. Streamed over SSE with plain httpx.

Set NUDGY_LLM_PROVIDER=openai_compatible, NUDGY_GATEWAY_URL, NUDGY_GATEWAY_KEY and
NUDGY_LLM_MODEL (one of the names the service lists at GET <gateway>/v1/models). If its models
can't read images, set NUDGY_LLM_VISION=false: Nudgy then sends only the UI element list,
which is still enough to point at named buttons. The same gateway can also do speech-to-text
and the voice (see http_stt.py / http_tts.py).
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import httpx

from app.providers.base import ImagePart, Message, ProviderError, Usage


def v1_url(base_url: str, path: str) -> str:
    """`http://host:port` or `http://host:port/v1` + `/chat/completions` → the full URL."""
    base = base_url.rstrip("/")
    return f"{base}{path}" if base.endswith("/v1") else f"{base}/v1{path}"


def to_openai(system: str, messages: list[Message], vision: bool) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        texts = [p for p in m.parts if isinstance(p, str)]
        images = [p for p in m.parts if isinstance(p, ImagePart)] if vision else []
        if not images:
            out.append({"role": m.role, "content": "\n\n".join(texts)})
            continue
        content: list[dict] = [{"type": "text", "text": t} for t in texts]
        for img in images:
            data = base64.standard_b64encode(img.data).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{img.media_type};base64,{data}"}}
            )
        out.append({"role": m.role, "content": content})
    return out


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
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not base_url:
            raise ProviderError("config", "NUDGY_GATEWAY_URL is not set")
        self.url = v1_url(base_url, "/chat/completions")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
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
        body = {
            "model": self.model,
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
