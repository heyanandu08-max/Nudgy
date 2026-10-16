#!/usr/bin/env python3
"""Downloads the open-source AI engines Nudgy bundles: llama.cpp's llama-server and
whisper.cpp's whisper-server (prebuilt releases from GitHub), into app/src-tauri/engines/.

    python3 scripts/fetch_engines.py windows    # CI (test-build.yml)
    python3 scripts/fetch_engines.py linux      # the local-AI check (local-ai-check.yml)

Set GITHUB_TOKEN to avoid API rate limits. Prints the release tags it used.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "src-tauri" / "engines"

# (engine folder, GitHub repo, asset name pattern per platform, program to find)
ENGINES = {
    "llama": (
        "ggml-org/llama.cpp",
        {
            "windows": r"^llama-b\d+-bin-win-cpu-x64\.zip$",
            "linux": r"^llama-b\d+-bin-ubuntu-x64\.zip$",
        },
        "llama-server",
    ),
    "whisper": (
        "ggml-org/whisper.cpp",
        {"windows": r"^whisper-bin-x64\.zip$", "linux": None},
        "whisper-server",
    ),
}


def get(url: str) -> bytes:
    headers = {"User-Agent": "nudgy-build"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as r:
        return r.read()


def fetch(folder: str, platform: str) -> None:
    repo, patterns, program = ENGINES[folder]
    pattern = patterns[platform]
    if pattern is None:
        print(f"{folder}: no prebuilt {platform} release; skipped")
        return
    release = json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest"))
    asset = next((a for a in release["assets"] if re.match(pattern, a["name"])), None)
    if asset is None:
        names = ", ".join(a["name"] for a in release["assets"])
        raise SystemExit(f"{repo} {release['tag_name']}: no asset matches {pattern}: {names}")
    print(f"{folder}: {repo} {release['tag_name']} {asset['name']}")
    data = zipfile.ZipFile(io.BytesIO(get(asset["browser_download_url"])))
    exe = program + (".exe" if platform == "windows" else "")
    found = [n for n in data.namelist() if n.split("/")[-1] == exe]
    if not found:
        raise SystemExit(f"{asset['name']} has no {exe}")
    # Copy the folder that holds the program, with its libraries, flat into engines/<folder>.
    prefix = found[0].rsplit("/", 1)[0] + "/" if "/" in found[0] else ""
    target = OUT / folder
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for name in data.namelist():
        if name.endswith("/") or not name.startswith(prefix) or "/" in name[len(prefix) :]:
            continue
        dest = target / name[len(prefix) :]
        dest.write_bytes(data.read(name))
        if platform != "windows":
            dest.chmod(0o755)
    print(f"  -> {target.relative_to(ROOT)} ({len(list(target.iterdir()))} files)")


def main() -> int:
    platform = sys.argv[1] if len(sys.argv) > 1 else "windows"
    for folder in ENGINES:
        fetch(folder, platform)
    return 0


if __name__ == "__main__":
    sys.exit(main())
