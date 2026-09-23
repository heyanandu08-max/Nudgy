"""Deterministic providers for tests, the smoke test and key-less local development."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from app.providers.base import ImagePart, Message, Usage

_WORD = re.compile(r"[a-z0-9]+")
_ELEMENT_LINE = re.compile(r"^(e\d+) \| ([^|]*) \| ([^|]*) \|", re.MULTILINE)
_USER_SAID = re.compile(r'User said: "(.*)"', re.DOTALL)


def _words(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if len(w) > 2}


class FakeLLM:
    """Points at the listed element whose name best overlaps the user's words."""

    name = "fake"

    def __init__(self, scripted: list[str] | None = None, chunk: int = 7):
        self.scripted = list(scripted or [])
        self.chunk = chunk
        self.calls: list[dict] = []

    def _answer(self, messages: list[Message]) -> str:
        text = "\n".join(p for p in messages[-1].parts if isinstance(p, str))
        said = (m.group(1) if (m := _USER_SAID.search(text)) else text).strip()
        want = _words(said)
        best, best_score = None, 0
        for el_id, _role, name in _ELEMENT_LINE.findall(text):
            score = len(want & _words(name))
            if score > best_score:
                best, best_score = (el_id, name.strip()), score
        if best:
            speech = f"Click {best[1]}. I've pointed at it for you."
            target = {"element_id": best[0]}
            hint = "click"
        else:
            speech = "I couldn't spot that on screen, but I'm happy to explain it."
            target, hint = None, None
        return json.dumps({"speech": speech, "target": target, "action_hint": hint})

    async def stream(
        self, *, system: str, messages: list[Message], max_tokens: int, usage: Usage
    ) -> AsyncIterator[str]:
        self.calls.append({"system": system, "messages": messages})
        out = self.scripted.pop(0) if self.scripted else self._answer(messages)
        for i in range(0, len(out), self.chunk):
            yield out[i : i + self.chunk]
        usage.input_tokens += sum(
            len(p) // 4 if isinstance(p, str) else 1000 for m in messages for p in m.parts
        )
        usage.output_tokens += len(out) // 4

    @staticmethod
    def has_image(messages: list[Message]) -> bool:
        return any(isinstance(p, ImagePart) for m in messages for p in m.parts)


class FakeSTT:
    name = "fake"

    def __init__(self, transcript: str = "How do I change the font?"):
        self.transcript = transcript

    async def transcribe(self, audio: bytes, *, mime: str, language: str) -> str:
        return self.transcript if audio else ""


class FakeTTS:
    name = "fake"
    mime = "audio/mpeg"

    async def synthesize(self, text: str, *, voice_id: str | None, language: str) -> bytes:
        return b"FAKEMP3:" + text.encode()
