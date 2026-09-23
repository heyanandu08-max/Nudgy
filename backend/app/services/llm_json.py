"""Ask the LLM for one JSON object matching a Pydantic model; repair once on failure."""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.providers.base import LLMProvider, Message, Usage, collect
from app.services.json_parse import extract_json_object
from app.services.prompts import load_prompt

log = logging.getLogger("nudgy.llm_json")

M = TypeVar("M", bound=BaseModel)


def parse_model(raw: str, model: type[M]) -> M | None:
    obj = extract_json_object(raw)
    if obj is None:
        return None
    try:
        return model.model_validate(obj)
    except ValidationError:
        return None


def repair_messages(messages: list[Message], raw: str, schema: str) -> list[Message]:
    return messages + [
        Message(role="assistant", parts=[raw or "(empty)"]),
        Message(
            role="user",
            parts=[load_prompt("repair_json").render(previous=raw[:4000], schema=schema)],
        ),
    ]


async def llm_json(
    llm: LLMProvider,
    *,
    system: str,
    messages: list[Message],
    model: type[M],
    schema: str,
    usage: Usage,
    max_tokens: int = 4096,
    effort: str | None = None,
) -> M | None:
    """Returns the parsed model, or None if two attempts both failed to validate."""
    raw = await collect(
        llm, system=system, messages=messages, max_tokens=max_tokens, usage=usage, effort=effort
    )
    if (parsed := parse_model(raw, model)) is not None:
        return parsed
    log.warning("%s JSON invalid; retrying once (len=%d)", model.__name__, len(raw))
    raw2 = await collect(
        llm,
        system=system,
        messages=repair_messages(messages, raw, schema),
        max_tokens=max_tokens,
        usage=usage,
        effort=effort,
    )
    return parse_model(raw2, model)
