# Decisions

Each entry: the decision, why, and what would make us revisit it.

## D1 — Monorepo layout: `app/` + `backend/` at the repo root
The brief's `nudgy/` folder is the repo root itself. One repo keeps the SSE event
schema, prompts and `.nudgy` format changes atomic across app and backend.

## D2 — Settings persisted as JSON by Rust, not in SQLite
Settings are tiny, read at startup before the DB is needed, and must be readable
by the hotkey/overlay code in Rust. Stored at `<app_config_dir>/settings.json`.
Learning data (skills, lessons, reviews, walkthroughs) goes in SQLite via `rusqlite`
(bundled) from Phase 4 — `rusqlite` over `tauri-plugin-sql` so the lesson runner and
recorder in Rust can write without a JS round-trip.

## D3 — Ask transport: multipart POST, Server-Sent Events response
One request carries audio + screenshot + context; the response is an SSE stream of
typed events. SSE works through proxies, is trivially testable with `httpx`, and needs
no WebSocket infrastructure. Streaming STT from the mic (Deepgram live) is a later
latency optimisation: push-to-talk clips are short, so upload-on-release is simpler
and meets the ~2.5 s target when TTS is streamed sentence-by-sentence.

## D4 — The Rust side makes backend HTTP calls, the webview renders
`reqwest` in Rust streams `/v1/ask` and forwards events to the overlay via Tauri
events. Screenshots never pass through the webview, and CORS / mixed content are
non-issues. Settings, health and dashboard calls may use `fetch` from the webview
(backend allows the Tauri origins via CORS).

## D5 — Coordinates: physical pixels, top-left origin, virtual desktop space
Single canonical space for all rects; conversions live in `geometry.rs` and are unit
tested (DPI, Retina, multi-monitor, negative offsets, macOS origin flip). See PLAN §1.

## D6 — Default models / providers (configurable via env)
- LLM: Anthropic, `NUDGY_LLM_MODEL=claude-sonnet-5` (Sonnet-class, vision). Model ID
  lives only in config.
- STT: Deepgram `nova-3` default; OpenAI Whisper fallback.
- TTS: ElevenLabs default; OpenAI TTS fallback.
- Each has a `fake` provider used by tests, the smoke test, and local dev without keys.

## D7 — Default hotkey
`Ctrl+Alt+Space` (Windows) / `Control+Option+Space` (macOS) — same accelerator string
`Ctrl+Alt+Space` in `tauri-plugin-global-shortcut`, which maps Alt → Option on macOS.
Push-to-talk uses the plugin's Pressed/Released states.

## D8 — Frontend state and styling
Zustand for state (small, no boilerplate), Tailwind for styling, `react-i18next` with
`en.json` only. Language list comes from `backend/config/languages.yaml` via
`/v1/config` with a bundled fallback so settings work offline.

## D9 — Backend Python tooling
`pyproject.toml` + pip (no Poetry/uv requirement) so contributors on any OS can
`pip install -e backend[dev]`. Pydantic Settings for config, SQLAlchemy 2.0, Alembic
added in Phase 7 when the schema starts to matter.

## D10 — Dev-environment verification limits
The repo is developed in a Linux container. Linux is not a v1 target, but the Tauri app
must still `cargo check`/`cargo test` there: OS-specific modules (`uitree`, overlay
click-through details, secure-field detection) have a `stub` implementation for other
targets. Items needing Windows/macOS hardware are marked `[~]` in PLAN.md.

## D11 — Privacy defaults
Screenshots are held in memory only, on both sides; the backend never writes request
bodies to disk or logs, and logs metadata only (sizes, tokens, latency). Walkthrough
sharing uploads step screenshots only if the author explicitly opts in per walkthrough.

## D12 — Overlay click-through toggled from Rust by cursor position
OS-level click-through is all-or-nothing per window, so the overlay registers its small
interactive regions (CSS px) via `set_interactive_regions`; the 60 Hz cursor loop turns
click-through off only while the cursor is inside one. Overlays are separate pages
(`overlay.html`) so the heavy settings/dashboard bundle never loads per monitor.

## D13 — Cross-target verification from Linux
`cargo check --target x86_64-pc-windows-msvc` and `--target aarch64-apple-darwin` (with clang)
work in the dev container, so all `cfg(target_os)` code is at least type-checked against the real
Windows and macOS APIs before it reaches hardware testing (`scripts/check_targets.sh`).

## D14 — Native TLS for the desktop HTTP client
`reqwest` uses `native-tls` (SChannel on Windows, Security.framework on macOS): it honours the
OS certificate store — important behind corporate TLS-inspecting proxies — and avoids a C
toolchain per target (the rustls/aws-lc default broke cross-target checks).

## D15 — Capture on key-down, send on key-up
The screenshot and UI tree are captured on a worker thread as soon as the hotkey goes down,
in parallel with the user speaking, which removes ~0.3–0.8 s from the critical path. A short tap
(<250 ms) discards everything. The typed-question path captures on the second tap, before the
text box takes focus, so the tree describes the user's app rather than Nudgy's box.

## D16 — Speech streamed from partial JSON, TTS per sentence
The talk prompt puts `"speech"` first; the backend decodes that string incrementally from the
streaming JSON, forwards caption deltas immediately, and synthesizes each finished sentence
while the model is still writing. Audio clips carry a `seq` and the overlay plays them in order.
The target arrives when the JSON completes. Invalid JSON → one repair request → speech-only.

## D17 — LLM defaults tuned for latency
`claude-sonnet-5` with thinking disabled and `effort: low` for talk mode (both env-configurable:
`NUDGY_LLM_THINKING`, `NUDGY_LLM_EFFORT`). Answers are 2–4 spoken sentences; lessons and step
verification (Phase 4) can use higher effort because they are not on the push-to-talk path.

## D18 — Vendor HTTP adapters verified by contract tests only
Deepgram, Whisper, ElevenLabs and OpenAI TTS adapters are tested against mocked transports
(request shape, auth header, error mapping). No vendor keys exist in the dev container, so the
first real call happens during hardware testing; endpoint details may need adjustment then.
