"""Provider interfaces. Every AI vendor sits behind one of these so it can be swapped by
config (NUDGY_LLM_PROVIDER / NUDGY_STT_PROVIDER / NUDGY_TTS_PROVIDER), not code."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol


class ProviderError(Exception):
    """A vendor call failed. `code` is stable and safe to show to the app."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    media_type: str = "image/jpeg"


Part = str | ImagePart


@dataclass
class Message:
    role: Literal["user", "assistant"]
    parts: list[Part]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    extra: dict[str, int] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    def stream(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int,
        usage: Usage,
        effort: str | None = None,
    ) -> AsyncIterator[str]:
        """Yields text deltas. Fills `usage` once the stream finishes. `effort` overrides the
        provider's default reasoning effort for this call (ignored by providers without one)."""
        ...


class STTProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, *, mime: str, language: str) -> str: ...


class TTSProvider(Protocol):
    name: str
    mime: str

    async def synthesize(self, text: str, *, voice_id: str | None, language: str) -> bytes:
        """Returns one complete, independently playable clip for `text`."""
        ...


async def collect(llm: LLMProvider, **kwargs) -> str:
    return "".join([d async for d in llm.stream(**kwargs)])
