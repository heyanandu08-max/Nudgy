#!/usr/bin/env python3
"""Runs the full ask pipeline (STT → LLM → TTS) against a saved screenshot + audio file,
without the desktop UI.

    # in-process, using the providers configured in .env (fake ones need no keys):
    python scripts/smoke_test.py
    # against a running backend:
    python scripts/smoke_test.py --url http://127.0.0.1:8787
    # keep the synthesized speech:
    python scripts/smoke_test.py --save-audio /tmp/nudgy-audio

Exits non-zero if the stream errors or never finishes. Prints per-stage timings.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "backend"))


def parse_sse_lines(lines):
    event = None
    for line in lines:
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: ") and event:
            yield event, json.loads(line[6:])
            event = None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="backend base URL; default runs the app in-process")
    ap.add_argument("--screenshot", type=Path, default=FIXTURES / "notepad.jpg")
    ap.add_argument("--audio", type=Path, default=FIXTURES / "question.wav")
    ap.add_argument("--context", type=Path, default=FIXTURES / "notepad_context.json")
    ap.add_argument("--text", help="ask this typed question instead of sending audio")
    ap.add_argument("--token", help="bearer token, if the backend requires sign-in")
    ap.add_argument("--save-audio", type=Path, help="directory to write the reply clips to")
    args = ap.parse_args()

    context = json.loads(args.context.read_text())
    if args.text:
        context["text"] = args.text
    files = {"screenshot": ("screen.jpg", args.screenshot.read_bytes(), "image/jpeg")}
    if not args.text:
        files["audio"] = ("question.wav", args.audio.read_bytes(), "audio/wav")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}

    if args.url:
        import httpx

        client = httpx.Client(base_url=args.url, timeout=60)
    else:
        from fastapi.testclient import TestClient

        from app.main import create_app

        client = TestClient(create_app())

    start = time.perf_counter()
    elapsed = lambda: f"{(time.perf_counter() - start) * 1000:7.0f} ms"  # noqa: E731
    ok = False
    clips = []
    with client.stream("POST", "/v1/ask", data={"context": json.dumps(context)}, files=files, headers=headers) as resp:
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}: {resp.read().decode(errors='replace')}")
            return 1
        speech = ""
        for event, data in parse_sse_lines(resp.iter_lines()):
            if event == "speech_text":
                speech += data["delta"]
                continue
            if event == "audio":
                clips.append(base64.b64decode(data["b64"]))
                print(f"{elapsed()}  audio #{data['seq']}: {len(clips[-1])} bytes — {data['text']!r}")
                continue
            print(f"{elapsed()}  {event}: {json.dumps(data)[:300]}")
            if event == "error" and data.get("fatal") is not False:
                return 1
            if event == "done":
                ok = True
                print(f"\nNudgy said: {speech}")
                print("Server timings (ms):", data["timings"])

    if args.save_audio and clips:
        args.save_audio.mkdir(parents=True, exist_ok=True)
        for i, clip in enumerate(clips):
            (args.save_audio / f"reply_{i}.mp3").write_bytes(clip)
        print(f"Saved {len(clips)} clip(s) to {args.save_audio}")
    if not ok:
        print("stream ended without a done event")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
