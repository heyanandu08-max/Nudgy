"""Tutor mode: plan a lesson, verify a step, locate a step's target, speak a line."""

from __future__ import annotations

import base64
import logging

from app.providers.base import ImagePart, Message, ProviderError, TTSProvider, Usage
from app.providers.registry import Providers
from app.schemas.ask import AskContext, TalkResponse, UiElement
from app.schemas.lessons import (
    LESSON_PLAN_SCHEMA,
    LOCATE_SCHEMA,
    VERIFY_SCHEMA,
    LessonPlan,
    LocateContext,
    LocateResult,
    PlanContext,
    VerifyContext,
    VerifyResult,
)
from app.services.ask import LANGUAGE_NAMES, validate_target
from app.services.json_parse import SentenceChunker
from app.services.llm_json import llm_json
from app.services.prompts import load_prompt

log = logging.getLogger("nudgy.lessons")

MIN_STEPS, MAX_STEPS = 3, 8


def _lang(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def element_lines(elements: list[UiElement]) -> str:
    if not elements:
        return "(no element list available)"
    return "\n".join(
        f"{e.id} | {e.role} | {e.name.replace('|', '/')} | "
        f"{e.rect.x:.0f},{e.rect.y:.0f},{e.rect.w:.0f},{e.rect.h:.0f}"
        for e in elements
    )


def _user_message(text: str, screenshot: bytes | None) -> Message:
    parts: list = [ImagePart(screenshot)] if screenshot else []
    parts.append(text)
    return Message(role="user", parts=parts)


async def plan_lesson(
    ctx: PlanContext, screenshot: bytes | None, p: Providers, usage: Usage
) -> LessonPlan:
    system = load_prompt("lesson_plan").render(
        goal=ctx.goal,
        min_steps=str(MIN_STEPS),
        max_steps=str(MAX_STEPS),
        language=_lang(ctx.language),
    )
    app = f'Foreground app: {ctx.app.name} — "{ctx.app.title}"\n' if ctx.app else ""
    text = f"{app}UI elements (id | role | name | x,y,w,h):\n{element_lines(ctx.elements)}\n\nGoal: {ctx.goal}"
    plan = await llm_json(
        p.llm,
        system=system,
        messages=[_user_message(text, screenshot)],
        model=LessonPlan,
        schema=LESSON_PLAN_SCHEMA,
        usage=usage,
        max_tokens=8192,
        effort="medium",
    )
    if plan is None:
        raise ProviderError(
            "llm_bad_output", "Couldn't put a lesson together. Try rephrasing the goal."
        )
    return plan


def diff_elements(before: list[UiElement], after: list[UiElement], limit: int = 40) -> str:
    """What appeared / disappeared between two element lists (by role + name)."""
    key = lambda e: (e.role, e.name)
    b = {key(e) for e in before}
    a = {key(e) for e in after}
    added = [f"+ {r} '{n}'" for r, n in sorted(a - b) if n][:limit]
    removed = [f"- {r} '{n}'" for r, n in sorted(b - a) if n][:limit]
    if not added and not removed:
        return "(no element changes detected)"
    return "\n".join(added + removed)


async def verify_step(
    ctx: VerifyContext, screenshot: bytes | None, p: Providers, usage: Usage
) -> VerifyResult:
    system = load_prompt("verify_step").render(
        instruction=ctx.step.instruction,
        success_check=ctx.step.success_check,
        attempt=str(ctx.attempt),
        language=_lang(ctx.language),
    )
    text = (
        f"Element changes since the step started:\n{diff_elements(ctx.before.elements, ctx.after.elements)}\n\n"
        f"Current UI elements:\n{element_lines(ctx.after.elements[:150])}"
    )
    result = await llm_json(
        p.llm,
        system=system,
        messages=[_user_message(text, screenshot)],
        model=VerifyResult,
        schema=VERIFY_SCHEMA,
        usage=usage,
        max_tokens=1024,
        effort="low",
    )
    if result is None:
        # Can't tell — don't block the learner on our parsing problem.
        return VerifyResult(
            passed=False, hint="I couldn't quite tell. Say done again when you're ready."
        )
    return result


async def locate(
    ctx: LocateContext, screenshot: bytes | None, p: Providers, usage: Usage
) -> dict | None:
    # Cheap exact match first: same role and name (case-insensitive).
    if ctx.target and ctx.target.name:
        want_name, want_role = ctx.target.name.strip().lower(), ctx.target.role.strip().lower()
        for e in ctx.elements:
            if e.name.strip().lower() == want_name and (
                not want_role or e.role.lower() == want_role
            ):
                return {"element_id": e.id}
    description = ctx.description or (
        f"{ctx.target.role} named '{ctx.target.name}'" if ctx.target else "the next thing to click"
    )
    system = load_prompt("locate").render(description=description)
    found = await llm_json(
        p.llm,
        system=system,
        messages=[_user_message(f"UI elements:\n{element_lines(ctx.elements)}", screenshot)],
        model=LocateResult,
        schema=LOCATE_SCHEMA,
        usage=usage,
        max_tokens=512,
        effort="low",
    )
    if found is None:
        return None
    check = AskContext(elements=ctx.elements, screenshot=ctx.screenshot)
    return validate_target(TalkResponse(speech="", target=found.target), check)


async def speak(text: str, tts: TTSProvider, voice_id: str | None, language: str) -> list[dict]:
    chunker = SentenceChunker()
    sentences = chunker.feed(text) + chunker.flush()
    clips = []
    for seq, sentence in enumerate(sentences):
        audio = await tts.synthesize(sentence, voice_id=voice_id, language=language)
        clips.append(
            {
                "seq": seq,
                "mime": tts.mime,
                "text": sentence,
                "b64": base64.b64encode(audio).decode(),
            }
        )
    return clips
