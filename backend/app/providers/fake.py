"""Deterministic providers for tests, the smoke test and key-less local development."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from app.providers.base import ImagePart, Message, Usage

_WORD = re.compile(r"[a-z0-9]+")
_ELEMENT_LINE = re.compile(r"^(e\d+) \| ([^|]*) \| ([^|]*) \|", re.MULTILINE)
_USER_SAID = re.compile(r'User said: "(.*)"', re.DOTALL)


_INTENTS = [
    ("teach me", "start_lesson"),
    ("i did it", "done"),
    ("done", "done"),
    ("skip", "skip"),
    ("show me", "show_me"),
    ("stop the lesson", "stop_lesson"),
]

EXCEL_LESSON = {
    "title": "Add up a column and show it as money",
    "app": "Excel",
    "skill": "excel.sum_and_currency",
    "skill_name": "SUM formulas and currency format",
    "steps": [
        {
            "instruction": "Click the empty cell right under your numbers, B7.",
            "target": {"role": "cell", "name": "B7"},
            "action_hint": "click",
            "success_check": "Cell B7 is selected (the Name Box shows B7).",
            "why": "The total goes directly under the numbers it adds up.",
        },
        {
            "instruction": "Type equals, SUM, open bracket, B2 colon B6, close bracket.",
            "target": None,
            "action_hint": "type",
            "success_check": "Cell B7 contains the formula =SUM(B2:B6).",
            "why": "SUM adds every cell in the range, so the total updates when numbers change.",
        },
        {
            "instruction": "Press Enter to finish the formula.",
            "target": None,
            "action_hint": "type",
            "success_check": "Cell B7 shows the total of B2 to B6 instead of the formula text.",
            "why": "Enter tells Excel you're done editing, so it calculates the result.",
        },
        {
            "instruction": "Now select the numbers and the total, from B2 down to B7.",
            "target": {"role": "cell", "name": "B2"},
            "action_hint": "drag",
            "success_check": "Cells B2 to B7 are highlighted.",
            "why": "Formatting applies to whatever is selected.",
        },
        {
            "instruction": "On the Home tab, click the Accounting Number Format button, the one with the money icon.",
            "target": {"role": "splitbutton", "name": "Accounting Number Format"},
            "action_hint": "click",
            "success_check": "Cells B2 to B7 show a currency symbol and two decimals.",
            "why": "Currency format makes it obvious these numbers are money and lines up the decimals.",
        },
    ],
}


def _words(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if len(w) > 2}


class FakeLLM:
    """Points at the listed element whose name best overlaps the user's words."""

    name = "fake"

    def __init__(self, scripted: list[str] | None = None, chunk: int = 7):
        self.scripted = list(scripted or [])
        self.chunk = chunk
        self.calls: list[dict] = []

    def _route(self, system: str, messages: list[Message]) -> str:
        if "hands-on lesson" in system:
            return json.dumps(EXCEL_LESSON)
        if "completed one step" in system:
            return self._verify(system, messages)
        if "Find a UI element" in system:
            return self._locate(system, messages)
        if "reusable walkthrough" in system:
            return self._clean(messages)
        return self._answer(messages)

    @staticmethod
    def _verify(system: str, messages: list[Message]) -> str:
        text = "\n".join(p for p in messages[-1].parts if isinstance(p, str))
        changed = "(no element changes detected)" not in text
        second_try = "attempt 1." not in system
        if changed or second_try:
            return json.dumps({"passed": True, "hint": "Nice work, that's exactly it!"})
        return json.dumps({"passed": False, "hint": "Not quite yet. Look for it near the top."})

    @staticmethod
    def _locate(system: str, messages: list[Message]) -> str:
        text = "\n".join(p for p in messages[-1].parts if isinstance(p, str))
        want = _words(system.split("Looking for:", 1)[-1].split("\n", 1)[0])
        for el_id, _role, name in _ELEMENT_LINE.findall(text):
            if want & _words(name):
                return json.dumps({"target": {"element_id": el_id}})
        return json.dumps({"target": None})

    @staticmethod
    def _clean(messages: list[Message]) -> str:
        text = "\n".join(p for p in messages[-1].parts if isinstance(p, str))
        steps = []
        for i, line in enumerate(re.findall(r"^\d+\. (.+?)(?: in .+)?$", text, re.MULTILINE)):
            if line.startswith("click ") and "'" in line:
                role, name = line[6:].split(" '", 1)
                target = {"role": role, "name": name.rstrip("'")}
                steps.append(
                    {
                        "instruction": f"Click {target['name']}.",
                        "target": target,
                        "action_hint": "click",
                        "raw": [i],
                    }
                )
            elif line.startswith("type "):
                steps.append(
                    {
                        "instruction": f"Type {line[5:]}.",
                        "target": None,
                        "action_hint": "type",
                        "raw": [i],
                    }
                )
            else:
                steps.append(
                    {
                        "instruction": f"{line[0].upper()}{line[1:]}.",
                        "target": None,
                        "action_hint": "type",
                        "raw": [i],
                    }
                )
        if not steps:
            steps = [{"instruction": "Follow along.", "raw": []}]
        return json.dumps(
            {
                "title": "Recorded walkthrough",
                "app": "",
                "summary": "Recorded with Nudgy.",
                "steps": steps,
            }
        )

    def _answer(self, messages: list[Message]) -> str:
        text = "\n".join(p for p in messages[-1].parts if isinstance(p, str))
        said = (m.group(1) if (m := _USER_SAID.search(text)) else text).strip()
        want = _words(said)
        best, best_score = None, 0
        for el_id, _role, name in _ELEMENT_LINE.findall(text):
            score = len(want & _words(name))
            if score > best_score:
                best, best_score = (el_id, name.strip()), score
        low = said.lower()
        for phrase, intent in _INTENTS:
            if low.startswith(phrase):
                goal = said[len(phrase) :].strip(" .?!") if intent == "start_lesson" else None
                speech = "Let's do it together!" if goal else "Okay!"
                return json.dumps(
                    {"speech": speech, "target": None, "intent": intent, "lesson_goal": goal}
                )
        if best:
            speech = f"Click {best[1]}. I've pointed at it for you."
            target = {"element_id": best[0]}
            hint = "click"
        else:
            speech = "I couldn't spot that on screen, but I'm happy to explain it."
            target, hint = None, None
        return json.dumps({"speech": speech, "target": target, "action_hint": hint})

    async def stream(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int,
        usage: Usage,
        effort: str | None = None,
    ) -> AsyncIterator[str]:
        self.calls.append({"system": system, "messages": messages, "effort": effort})
        out = self.scripted.pop(0) if self.scripted else self._route(system, messages)
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
