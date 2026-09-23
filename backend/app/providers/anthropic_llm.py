from __future__ import annotations

import base64
from collections.abc import AsyncIterator

import anthropic

from app.providers.base import ImagePart, Message, ProviderError, Usage


def _to_api(messages: list[Message]) -> list[dict]:
    out = []
    for m in messages:
        content = []
        for p in m.parts:
            if isinstance(p, ImagePart):
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": p.media_type,
                            "data": base64.standard_b64encode(p.data).decode("ascii"),
                        },
                    }
                )
            else:
                content.append({"type": "text", "text": p})
        out.append({"role": m.role, "content": content})
    return out


class AnthropicLLM:
    """Claude vision model via the official SDK, streamed."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        thinking: str = "disabled",
        effort: str | None = "low",
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ProviderError("config", "ANTHROPIC_API_KEY is not set")
        self.client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=1)
        self.model = model
        self.thinking = thinking
        self.effort = effort

    async def stream(
        self, *, system: str, messages: list[Message], max_tokens: int, usage: Usage
    ) -> AsyncIterator[str]:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": _to_api(messages),
        }
        # Spoken answers are short and latency-bound (first audio ≤ 2.5 s), so thinking
        # defaults to off with low effort; both are configurable per deployment.
        if self.thinking == "disabled":
            kwargs["thinking"] = {"type": "disabled"}
        elif self.thinking == "adaptive":
            kwargs["thinking"] = {"type": "adaptive"}
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        try:
            async with self.client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except anthropic.RateLimitError as e:
            raise ProviderError("llm_rate_limited", str(e), retryable=True) from e
        except anthropic.AuthenticationError as e:
            raise ProviderError("llm_auth", "LLM credentials were rejected") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(
                "llm_failed", f"LLM error {e.status_code}", retryable=e.status_code >= 500
            ) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("llm_unreachable", "Could not reach the LLM", retryable=True) from e

        if final.stop_reason == "refusal":
            raise ProviderError("llm_refused", "The model declined this request")
        usage.input_tokens += final.usage.input_tokens
        usage.output_tokens += final.usage.output_tokens
