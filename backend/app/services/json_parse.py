"""Parsing helpers for model output: tolerant JSON extraction, incremental extraction of
the `speech` string while the JSON is still streaming, and sentence chunking for TTS."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Returns the first complete top-level JSON object in `text`, or None.

    Tolerates code fences and prose around the object (models sometimes add them)."""
    s = _FENCE.sub("", text.strip())
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start : i + 1])
                    except json.JSONDecodeError:
                        break
                    return obj if isinstance(obj, dict) else None
        start = s.find("{", start + 1)
    return None


_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class StringFieldExtractor:
    """Streams the decoded value of one top-level string field (e.g. "speech") out of JSON
    that is still arriving in arbitrary chunks. `feed` returns newly decoded characters."""

    def __init__(self, key: str = "speech"):
        self._needle = f'"{key}"'
        self._buf = ""
        self._pos = 0  # scan position in _buf
        self._state = "seek_key"  # seek_key → seek_colon → seek_quote → in_value → done
        self._pending_escape = ""
        self.value = ""

    @property
    def done(self) -> bool:
        return self._state == "done"

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: list[str] = []
        while self._pos < len(self._buf) and self._state != "done":
            if self._state == "seek_key":
                idx = self._buf.find(self._needle, self._pos)
                if idx == -1:
                    # Keep enough tail to match a key split across chunks.
                    self._pos = max(self._pos, len(self._buf) - len(self._needle))
                    break
                self._pos = idx + len(self._needle)
                self._state = "seek_colon"
            elif self._state in ("seek_colon", "seek_quote"):
                ch = self._buf[self._pos]
                self._pos += 1
                if ch.isspace():
                    continue
                if self._state == "seek_colon":
                    self._state = "seek_quote" if ch == ":" else "seek_key"
                else:
                    self._state = "in_value" if ch == '"' else "seek_key"
            else:  # in_value
                ch = self._buf[self._pos]
                if self._pending_escape or ch == "\\":
                    seq = self._pending_escape + ch
                    self._pos += 1
                    decoded = self._decode_escape(seq)
                    if decoded is None:
                        self._pending_escape = seq  # need more characters
                        continue
                    self._pending_escape = ""
                    out.append(decoded)
                elif ch == '"':
                    self._pos += 1
                    self._state = "done"
                else:
                    self._pos += 1
                    out.append(ch)
        new = "".join(out)
        self.value += new
        return new

    @staticmethod
    def _decode_escape(seq: str) -> str | None:
        if len(seq) < 2:
            return None
        kind = seq[1]
        if kind == "u":
            if len(seq) < 6:
                return None
            try:
                return chr(int(seq[2:6], 16))
            except ValueError:
                return ""
        return _ESCAPES.get(kind, kind)


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")


class SentenceChunker:
    """Groups streamed text into sentence-sized pieces for per-sentence TTS. Very short
    sentences are merged forward so we don't synthesize one-word clips."""

    def __init__(self, min_chars: int = 24):
        self.min_chars = min_chars
        self._buf = ""

    def feed(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        while True:
            m = _SENTENCE_END.search(self._buf)
            if not m:
                break
            candidate = self._buf[: m.start()].strip()
            if len(candidate) < self.min_chars:
                # Look for a later boundary so the chunk is long enough.
                later = _SENTENCE_END.search(self._buf, m.end())
                if not later:
                    break
                candidate = self._buf[: later.start()].strip()
                self._buf = self._buf[later.end() :]
            else:
                self._buf = self._buf[m.end() :]
            if candidate:
                out.append(candidate)
        return out

    def flush(self) -> list[str]:
        rest, self._buf = self._buf.strip(), ""
        return [rest] if rest else []
