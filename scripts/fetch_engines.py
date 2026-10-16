#!/usr/bin/env python3
"""Downloads the open-source AI engines Nudgy bundles: llama.cpp's llama-server and
whisper.cpp's whisper-server (prebuilt releases from GitHub), into app/src-tauri/engines/.

    python3 scripts/fetch_engines.py windows    # CI (test-build.yml)
    python3 scripts/fetch_engines.py linux      # the built-in AI check (local-ai-check.yml)

Set GITHUB_TOKEN to avoid API rate limits. Prints the releases it used.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "src-tauri" / "engines"

# folder -> (GitHub repo, asset name pattern per platform, program to find)
ENGINES = {
    "llama": (
        "ggml-org/llama.cpp",
        {
            "windows": r"^llama-.*bin-win-cpu-x64\.zip$",
            "linux": r"^llama-.*bin-ubuntu-x64\.(zip|tar\.gz)$",
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


def pick(repo: str, pattern: str) -> tuple[dict, dict]:
    """The newest published release with a matching file ("latest" isn't always an engine build)."""
    releases = json.loads(get(f"https://api.github.com/repos/{repo}/releases?per_page=40"))
    for release in releases:
        if release.get("draft"):
            continue
        for asset in release["assets"]:
            if re.match(pattern, asset["name"]):
                return release, asset
    seen = "\n".join(
        f"  {r['tag_name']}: " + ", ".join(a["name"] for a in r["assets"][:15]) for r in releases[:5]
    )
    raise SystemExit(f"{repo}: no release file matches {pattern}. Newest releases:\n{seen}")


def unpack(name: str, raw: bytes) -> dict[str, bytes]:
    """Every file in the archive, by path."""
    if name.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            # Libraries often come as symlinks (libx.so.0 -> libx.so.0.1): keep them as copies.
            return {
                m.name: tar.extractfile(m).read()
                for m in tar.getmembers()
                if m.isfile() or m.issym() or m.islnk()
            }
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}


def fetch(folder: str, platform: str) -> None:
    repo, patterns, program = ENGINES[folder]
    pattern = patterns[platform]
    if pattern is None:
        print(f"{folder}: no prebuilt {platform} release; skipped")
        return
    release, asset = pick(repo, pattern)
    print(f"{folder}: {repo} {release['tag_name']} {asset['name']}")
    files = unpack(asset["name"], get(asset["browser_download_url"]))
    exe = program + (".exe" if platform == "windows" else "")
    found = [n for n in files if n.split("/")[-1] == exe]
    if not found:
        raise SystemExit(f"{asset['name']} has no {exe}: {list(files)[:20]}")
    # Copy the folder that holds the program, with its libraries, flat into engines/<folder>.
    prefix = found[0].rsplit("/", 1)[0] + "/" if "/" in found[0] else ""
    target = OUT / folder
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    is_lib = re.compile(r"\.(dll|so(\.\d+)*|dylib)$")
    for name, data in files.items():
        beside = name.startswith(prefix) and "/" not in name[len(prefix) :]
        if not beside and not is_lib.search(name):  # libraries may sit in a lib/ folder
            continue
        dest = target / name.split("/")[-1]
        dest.write_bytes(data)
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
