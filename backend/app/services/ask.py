"""The ask pipeline: STT → prompt → LLM (streamed) → TTS per sentence → SSE events.

Events (see PLAN.md §1): transcript, speech_text, target, audio, done, error.
Screenshots and audio live only in memory for the duration of the request."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.providers.base import ImagePart, Message, ProviderError, Usage, collect
from app.providers.registry import Providers
from app.schemas.ask import AskContext, ElementTarget, PointTarget, TalkResponse
from app.services.json_parse import SentenceChunker, StringFieldExtractor, extract_json_object
from app.services.prompts import load_prompt

log = logging.getLogger("nudgy.ask")

LANGUAGE_NAMES = {"en": "English"}
LENGTH = {
    "brief": "2 to 4 short sentences unless the user explicitly asks for detail.",
    "detailed": "up to 8 sentences; explain the why as well as the how.",
}
MAX_TOKENS = 2048

Event = tuple[str, dict]


@dataclass
class AskInput:
    context: AskContext
    audio: bytes | None = None
    audio_mime: str = "audio/wav"
    screenshot: bytes | None = None
    screenshot_mime: str = "image/jpeg"


@dataclass
class Timings:
    start: float = field(default_factory=time.perf_counter)
    marks: dict[str, int] = field(default_factory=dict)

    def mark(self, name: str) -> None:
        self.marks.setdefault(name, round((time.perf_counter() - self.start) * 1000))


def system_prompt(ctx: AskContext) -> str:
    return load_prompt("talk").render(
        length_instruction=LENGTH[ctx.response_length],
        language=LANGUAGE_NAMES.get(ctx.language, ctx.language),
    )


def describe_screen(ctx: AskContext, transcript: str) -> str:
    lines = []
    if ctx.app and (ctx.app.name or ctx.app.title):
        lines.append(f'Foreground app: {ctx.app.name} — "{ctx.app.title}"')
    if ctx.screenshot:
        lines.append(f"Screenshot: {ctx.screenshot.width}x{ctx.screenshot.height} px.")
    else:
        lines.append("No screenshot is available for this question.")
    if ctx.elements:
        lines.append("UI elements (id | role | name | x,y,w,h in screenshot px):")
        for e in ctx.elements:
            r = e.rect
            name = e.name.replace("|", "/").replace("\n", " ").strip()
            lines.append(f"{e.id} | {e.role} | {name} | {r.x:.0f},{r.y:.0f},{r.w:.0f},{r.h:.0f}")
    else:
        lines.append("No UI element list is available; point with x,y if needed.")
    lines.append(f'User said: "{transcript}"')
    return "\n".join(lines)


def build_messages(
    ctx: AskContext, transcript: str, screenshot: bytes | None, mime: str
) -> list[Message]:
    messages: list[Message] = []
    for turn in ctx.history:
        # The API needs alternating roles starting with the user; merge any repeats.
        if messages and messages[-1].role == turn.role:
            messages[-1].parts.append(turn.text)
        elif messages or turn.role == "user":
            messages.append(Message(role=turn.role, parts=[turn.text]))
    if messages and messages[-1].role == "user":
        messages.pop()  # an unanswered question would make two user turns in a row
    parts: list = [ImagePart(screenshot, mime)] if screenshot else []
    parts.append(describe_screen(ctx, transcript))
    messages.append(Message(role="user", parts=parts))
    return messages


def validate_target(resp: TalkResponse, ctx: AskContext) -> dict | None:
    """Drops targets that don't exist on screen instead of pointing somewhere wrong."""
    t = resp.target
    if isinstance(t, ElementTarget):
        return (
            {"element_id": t.element_id}
            if any(e.id == t.element_id for e in ctx.elements)
            else None
        )
    if (
        isinstance(t, PointTarget)
        and ctx.screenshot
        and 0 <= t.x <= ctx.screenshot.width
        and 0 <= t.y <= ctx.screenshot.height
    ):
        return {"x": round(t.x), "y": round(t.y)}
    return None


def parse_talk(raw: str) -> TalkResponse | None:
    obj = extract_json_object(raw)
    if obj is None:
        return None
    try:
        return TalkResponse.model_validate(obj)
    except ValidationError:
        return None


async def run_ask(inp: AskInput, providers: Providers) -> AsyncIterator[Event]:
    """Yields (event, data) pairs. Never raises: failures become `error` events."""
    queue: asyncio.Queue[Event | None] = asyncio.Queue()
    task = asyncio.create_task(_produce(inp, providers, queue))
    try:
        while (item := await queue.get()) is not None:
            yield item
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _produce(inp: AskInput, p: Providers, out: asyncio.Queue[Event | None]) -> None:
    ctx = inp.context
    t = Timings()
    usage = Usage()
    put = out.put_nowait
    try:
        # 1. Transcript
        if ctx.text and ctx.text.strip():
            transcript = ctx.text.strip()
        elif inp.audio:
            transcript = await p.stt.transcribe(
                inp.audio, mime=inp.audio_mime, language=ctx.language
            )
            t.mark("stt_ms")
        else:
            transcript = ""
        if not transcript:
            put(("error", {"code": "no_speech", "message": "I didn't catch that."}))
            return
        put(("transcript", {"text": transcript}))

        # 2. TTS worker: synthesizes sentences in order while the LLM is still talking.
        sentences: asyncio.Queue[str | None] = asyncio.Queue()
        tts_task = (
            asyncio.create_task(_tts_worker(ctx, p, sentences, put, t))
            if ctx.voice_enabled
            else None
        )
        chunker = SentenceChunker()

        def speak(text: str) -> None:
            put(("speech_text", {"delta": text}))
            t.mark("first_text_ms")
            if tts_task:
                for s in chunker.feed(text):
                    sentences.put_nowait(s)

        # 3. LLM, streamed; the "speech" field is forwarded as it arrives.
        system = system_prompt(ctx)
        messages = build_messages(ctx, transcript, inp.screenshot, inp.screenshot_mime)
        extractor = StringFieldExtractor("speech")
        raw = ""
        async for delta in p.llm.stream(
            system=system, messages=messages, max_tokens=MAX_TOKENS, usage=usage
        ):
            t.mark("llm_first_token_ms")
            raw += delta
            if new := extractor.feed(delta):
                speak(new)
        t.mark("llm_ms")

        # 4. Validate; retry once with a "valid JSON only" nudge; then speech-only.
        resp = parse_talk(raw)
        if resp is None:
            log.warning("talk JSON invalid; retrying once (len=%d)", len(raw))
            repair = messages + [
                Message(role="assistant", parts=[raw or "(empty)"]),
                Message(
                    role="user", parts=[load_prompt("repair_json").render(previous=raw[:4000])]
                ),
            ]
            raw2 = await collect(
                p.llm, system=system, messages=repair, max_tokens=MAX_TOKENS, usage=usage
            )
            resp = parse_talk(raw2)
            t.mark("llm_repair_ms")
        if resp is None:
            speech = extractor.value or _plain_speech(raw)
            resp = TalkResponse(speech=speech or "Sorry, I got tongue-tied. Could you ask again?")

        if not extractor.value:
            speak(resp.speech)  # nothing was streamed (bad first reply) — say it now
        elif (
            not extractor.done
            and resp.speech.startswith(extractor.value)
            and (rest := resp.speech[len(extractor.value) :])
        ):
            speak(rest)  # the stream was cut mid-speech; the repair finished the sentence

        put(("target", {"target": validate_target(resp, ctx), "action_hint": resp.action_hint}))

        if tts_task:
            for s in chunker.flush():
                sentences.put_nowait(s)
            sentences.put_nowait(None)
            await tts_task
        t.mark("total_ms")
        put(("done", {"speech": resp.speech, "timings": t.marks, "usage": _usage(usage)}))
    except ProviderError as e:
        log.warning("ask failed: %s (%s)", e.code, e)
        put(
            (
                "error",
                {"code": e.code, "message": str(e) if e.code == "config" else _friendly(e.code)},
            )
        )
    except Exception:
        log.exception("ask crashed")
        put(("error", {"code": "internal", "message": "Something went wrong on our side."}))
    finally:
        log.info(
            "ask done timings=%s in=%d out=%d elements=%d screenshot_bytes=%d audio_bytes=%d",
            t.marks,
            usage.input_tokens,
            usage.output_tokens,
            len(ctx.elements),
            len(inp.screenshot or b""),
            len(inp.audio or b""),
        )
        put(None)


async def _tts_worker(
    ctx: AskContext, p: Providers, sentences: asyncio.Queue, put, t: Timings
) -> None:
    seq = 0
    while (text := await sentences.get()) is not None:
        try:
            clip = await p.tts.synthesize(text, voice_id=ctx.voice_id, language=ctx.language)
        except ProviderError as e:
            # Captions still work without voice; report once and stop synthesizing.
            put(("error", {"code": e.code, "message": _friendly(e.code), "fatal": False}))
            while await sentences.get() is not None:
                pass
            return
        t.mark("first_audio_ms")
        put(
            (
                "audio",
                {
                    "seq": seq,
                    "mime": p.tts.mime,
                    "text": text,
                    "b64": base64.b64encode(clip).decode(),
                },
            )
        )
        seq += 1


def _plain_speech(raw: str) -> str:
    text = raw.strip().strip("`").strip()
    return "" if text.startswith("{") else text[:600]


def _usage(u: Usage) -> dict:
    return {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}


def _friendly(code: str) -> str:
    if code.startswith("stt"):
        return "I couldn't transcribe that. Mind trying again?"
    if code.startswith("tts"):
        return "My voice isn't working right now, so I'll just show captions."
    if code == "llm_refused":
        return "I can't help with that one."
    if code.startswith("llm"):
        return "My brain is a bit busy right now. Please try again in a moment."
    return "Something went wrong."
