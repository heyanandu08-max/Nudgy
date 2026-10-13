#!/usr/bin/env bash
# Renders the shared UI as Windows and macOS (scripts/ui_parity.mjs) and diffs each pair.
# Prints, per screen, how many pixels differ and the box that contains all differences, so
# anything beyond the allowed native bits (keyboard symbols) stands out.
# Usage: scripts/ui_parity.sh [out_dir]   (the frontend must be served on :1420)
set -euo pipefail
out="${1:-parity}"
node "$(dirname "$0")/ui_parity.mjs" "$out"
for win in "$out"/*-win.png; do
  name="$(basename "$win" -win.png)"
  mac="$out/$name-mac.png"
  diff="$out/$name-diff.png"
  px=$(compare -metric AE "$win" "$mac" "$diff" 2>&1 >/dev/null || true)
  box=$(compare "$win" "$mac" -compose src -highlight-color black -lowlight-color white miff:- 2>/dev/null \
        | convert - -negate -trim -format '%wx%h%X%Y' info: 2>/dev/null || echo "-")
  [ "$px" = "0" ] && box="-"
  printf '%-18s %8s px differ   box %s\n' "$name" "$px" "$box"
done
