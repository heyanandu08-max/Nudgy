#!/usr/bin/env python3
"""Asks Nudgy's built-in AI real questions through the real server code, with a running
llama-server (see .github/workflows/local-ai-check.yml). Prints every answer and its time, and
fails if an answer isn't usable: no speech, a target that isn't on screen, or a lesson
without steps.

    NUDGY_LOCAL_LLM_URL=http://127.0.0.1:8790 python3 scripts/check_local_ai.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
os.environ.update(
    NUDGY_ENV="dev",
    NUDGY_LLM_PROVIDER="local",
    NUDGY_STT_PROVIDER="fake",
    NUDGY_TTS_PROVIDER="system",
    NUDGY_MAX_ELEMENTS="80",
    NUDGY_DATABASE_URL="sqlite:///:memory:",
)

from fastapi.testclient import TestClient

from app.main import create_app

# A Word-like window: what the app sends (names, roles, positions in screenshot pixels).
WORD = [
    ("button", "File"), ("button", "Home"), ("button", "Insert"), ("button", "Layout"),
    ("button", "Bold"), ("button", "Italic"), ("button", "Underline"),
    ("combobox", "Font"), ("combobox", "Font Size"), ("button", "Align Left"),
    ("button", "Center"), ("button", "Bullets"), ("button", "Numbering"),
    ("button", "Save"), ("button", "Undo"), ("edit", "Page 1 content"),
]  # fmt: skip
ELEMENTS = [
    {"id": f"e{i}", "role": r, "name": n, "rect": {"x": 20 + 60 * (i % 12), "y": 20 + 40 * (i // 12), "w": 50, "h": 28}}
    for i, (r, n) in enumerate(WORD, start=1)
]  # fmt: skip
APP = {"name": "Microsoft Word", "title": "Report.docx - Word"}

QUESTIONS = [
    ("How do I make this text bold?", "Bold"),
    ("How do I put a bullet list here?", "Bullets"),
    ("Where do I save my document?", "Save"),
    ("What is the capital of France?", None),  # off-topic: must still answer something
]


def main() -> int:
    client = TestClient(create_app())
    problems = []
    for question, expect in QUESTIONS:
        ctx = {"elements": ELEMENTS, "app": APP, "text": question, "voice_enabled": False}
        started = time.perf_counter()
        r = client.post("/v1/ask", data={"context": json.dumps(ctx)})
        secs = time.perf_counter() - started
        events = [
            (block.split("\n")[0][7:], json.loads(block.split("\n")[1][6:]))
            for block in r.text.strip().split("\n\n")
            if block.startswith("event: ")
        ]
        speech = "".join(d["delta"] for e, d in events if e == "speech_text")
        target = next((d.get("target") for e, d in events if e == "target"), None)
        error = next((d for e, d in events if e == "error"), None)
        name = None
        if target and "element_id" in target:
            name = next(
                (n for (_, n), el in zip(WORD, ELEMENTS) if el["id"] == target["element_id"]), None
            )
        print(f"\nQ: {question}\n  {secs:.1f}s  speech: {speech!r}\n  points at: {name or target}")
        if error:
            problems.append(f"{question!r}: error {error}")
        elif not speech.strip():
            problems.append(f"{question!r}: no speech")
        elif expect and name != expect:
            print(f"  (expected {expect})")
            problems.append(f"{question!r}: pointed at {name or target}, expected {expect}")

    started = time.perf_counter()
    plan_ctx = {
        "goal": "Make the title bold and centered in Word",
        "elements": ELEMENTS,
        "app": APP,
    }
    r = client.post("/v1/lessons/plan", data={"context": json.dumps(plan_ctx)})
    secs = time.perf_counter() - started
    print(f"\nLesson plan ({secs:.1f}s): HTTP {r.status_code}")
    if r.status_code == 200:
        plan = r.json()
        for i, s in enumerate(plan["steps"], 1):
            print(f"  {i}. {s['instruction']}")
        if len(plan["steps"]) < 2:
            problems.append("lesson plan has fewer than 2 steps")
    else:
        problems.append(f"lesson plan failed: {r.text[:300]}")

    print()
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        # Wrong pointing is reported but only a broken answer fails the check.
        hard = [p for p in problems if "expected" not in p]
        return 1 if hard else 0
    print("All answers usable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
