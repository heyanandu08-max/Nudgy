# CLAUDE.md

## Project
Nudgy — a cross-platform (Windows 10/11, macOS 13+) desktop AI tutor that lives next
to the cursor. Push-to-talk question → backend (STT → vision LLM → TTS) → spoken answer
+ animated pointer to the exact UI element. Also: verified step-by-step lessons, skill
tracking with spaced repetition, and recordable/shareable walkthroughs. Privacy-first:
capture only on demand, screenshots never stored.

`PLAN.md` = architecture + phase checklist (keep it ticked). `DECISIONS.md` = why.

## Stack
- `app/`: Tauri v2 (Rust) + React + Vite + TypeScript + Tailwind, zustand, react-i18next.
- `backend/`: Python 3.11+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2, httpx.
- AI providers behind interfaces in `backend/app/providers/` (LLM / STT / TTS), selected by env.
- LLM system prompts: `backend/prompts/*.md` (versioned; bump the `version:` header on change).

## Run
```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cp ../.env.example ../.env    # fill in keys, or keep the fake providers
uvicorn app.main:app --reload --port 8787

# app
cd app && npm install && npm run tauri dev
```

## Test / check
```bash
cd backend && pytest -q && ruff check .
cd app && npm run build            # tsc + vite
cd app/src-tauri && cargo test && cargo clippy
```
Linux needs the Tauri system deps (webkit2gtk-4.1, gtk3, libsoup-3, appindicator, alsa) to compile.

## Conventions
- All user-visible strings go through i18n (`app/src/i18n/locales/en.json`). No literals in JSX.
- OS-specific Rust lives in `cfg(target_os)` modules implementing a shared trait; always keep a `stub` for other targets so the crate compiles everywhere.
- Coordinates: physical pixels, top-left origin, virtual-desktop space. Convert only via `geometry.rs`.
- The desktop app never calls AI vendors directly — only the backend.
- Never persist or log screenshots/audio. Log metadata only.
- Every phase: build + tests pass, tick `PLAN.md`, one clear commit. Never start a phase on a broken build.
- Prefer small modules; no gold-plating.

## Secrets
**Never commit secrets.** Keys live in the git-ignored `.env`; `.env.example` documents every variable with a blank/placeholder value.
