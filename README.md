# Nudgy

Nudgy is an AI buddy that lives next to your cursor. It sees your screen, talks you
through any app, and points at exactly where to click.

> Status: early development. See [`PLAN.md`](PLAN.md) for the phase checklist.

## Layout
| Path        | What                                                            |
|-------------|-----------------------------------------------------------------|
| `app/`      | Desktop app: Tauri v2 (Rust) + React + Vite + TypeScript + Tailwind |
| `backend/`  | FastAPI proxy: AI providers, auth, usage limits, billing        |
| `docs/`     | Architecture notes, privacy policy draft                       |
| `scripts/`  | Smoke tests and tooling                                         |

## Quick start
Prerequisites: Node 20+, Rust (stable), Python 3.11+, and the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/) for your OS.

```bash
cp .env.example .env            # the default "fake" providers need no API keys

# backend
cd backend
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8787

# app (second terminal)
cd app
npm install
npm run tauri dev
```

Nudgy starts in the system tray / menu bar. Choose **Settings…** to open the settings
window; the badge in its header shows whether the backend is reachable.

## Environment variables
All documented in [`.env.example`](.env.example). Never commit `.env`.

## Tests
```bash
cd backend && pytest -q && ruff check .
cd app && npm run build
cd app/src-tauri && cargo test
```
