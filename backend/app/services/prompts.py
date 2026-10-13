"""Loads versioned system prompts from backend/prompts/*.md.

Each file starts with a front-matter block:
    ---
    name: talk
    version: 3
    ---
and uses {{placeholders}} filled by `render`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.config import PROMPTS_DIR

_FRONT = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    body: str

    def render(self, **values: str) -> str:
        def sub(m: re.Match) -> str:
            key = m.group(1)
            if key not in values:
                raise KeyError(f"prompt {self.name!r} needs {{{{{key}}}}}")
            return str(values[key])

        return _VAR.sub(sub, self.body)


@lru_cache
def load_prompt(name: str) -> Prompt:
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    if m := _FRONT.match(raw):
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        raw = raw[m.end() :]
    return Prompt(name=meta.get("name", name), version=meta.get("version", "0"), body=raw.strip())
