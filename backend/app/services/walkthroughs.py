"""Record & Replay: clean a raw recording into a walkthrough; share walkthroughs by link."""

from __future__ import annotations

import json
import logging
import secrets

from app.providers.base import Message, Usage
from app.providers.registry import Providers
from app.schemas.walkthrough import (
    CLEANED_SCHEMA,
    CleanedStep,
    CleanedWalkthrough,
    CleanRequest,
    RawStep,
)
from app.services.ask import LANGUAGE_NAMES
from app.services.llm_json import llm_json
from app.services.prompts import load_prompt

log = logging.getLogger("nudgy.walkthroughs")


def describe_raw(raw: list[RawStep]) -> str:
    lines = []
    for i, r in enumerate(raw):
        where = f" in {r.app}" + (f' — "{r.window}"' if r.window else "") if r.app else ""
        if r.kind == "click":
            what = (
                f"click {r.target.role} '{r.target.name}'"
                if r.target
                else "click (unknown element)"
            )
        elif r.kind == "type":
            what = f'type "{r.text or ""}"'
        else:
            what = f"press {r.keys or '?'}"
        note = f"  [author note: {r.note}]" if r.note else ""
        lines.append(f"{i}. {what}{where}{note}")
    return "\n".join(lines)


def fallback_clean(req: CleanRequest) -> CleanedWalkthrough:
    """Deterministic one-step-per-action conversion, used if the LLM output is unusable."""
    steps = []
    for i, r in enumerate(req.raw):
        if r.kind == "click" and r.target and r.target.name:
            text = f"Click {r.target.name}."
            hint = "click"
        elif r.kind == "type" and r.text and r.text != "[hidden]":
            text = f'Type "{r.text}".'
            hint = "type"
        elif r.kind == "type":
            text = "Type your text."
            hint = "type"
        elif r.keys:
            text = f"Press {r.keys}."
            hint = "type"
        else:
            continue
        steps.append(
            CleanedStep(
                instruction=text,
                target=r.target if r.kind == "click" else None,
                action_hint=hint,
                why=r.note or "",
                raw=[i],
            )
        )
    if not steps:
        steps = [CleanedStep(instruction="Follow along with the recording.", raw=[])]
    app = req.app or next((r.app for r in req.raw if r.app), "")
    return CleanedWalkthrough(
        title=f"Walkthrough in {app}" if app else "Walkthrough", app=app, steps=steps
    )


async def clean(req: CleanRequest, p: Providers, usage: Usage) -> CleanedWalkthrough:
    system = load_prompt("walkthrough_clean").render(
        language=LANGUAGE_NAMES.get(req.language, req.language)
    )
    text = f"App: {req.app or 'unknown'}\nRaw log:\n{describe_raw(req.raw)}"
    cleaned = await llm_json(
        p.llm,
        system=system,
        messages=[Message(role="user", parts=[text])],
        model=CleanedWalkthrough,
        schema=CLEANED_SCHEMA,
        usage=usage,
        max_tokens=8192,
        effort="medium",
    )
    if cleaned is None:
        log.warning("walkthrough clean fell back to deterministic steps")
        return fallback_clean(req)
    n = len(req.raw)
    for s in cleaned.steps:
        s.raw = [i for i in s.raw if 0 <= i < n]
    return cleaned


def new_slug() -> str:
    return secrets.token_urlsafe(9)  # 12 chars, ~72 bits


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
