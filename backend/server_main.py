"""Entry point for the packaged server (nudgy-server.exe, built with PyInstaller).

Double-click it: it serves Nudgy on http://127.0.0.1:8787 (NUDGY_HOST / NUDGY_PORT to change).
Settings and keys are read from the `.env` next to the program; on first run a starter `.env`
is written there from the bundled .env.example so there is something to fill in.
"""

import os
import shutil
import sys
from pathlib import Path


def _first_run_env() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    env = Path(sys.executable).resolve().parent / ".env"
    template = Path(getattr(sys, "_MEIPASS", ".")) / ".env.example"
    if not env.exists() and template.exists():
        shutil.copyfile(template, env)
    return env


def main() -> None:
    env = _first_run_env()
    host = os.environ.get("NUDGY_HOST", "127.0.0.1")
    port = int(os.environ.get("NUDGY_PORT", "8787"))

    import uvicorn

    from app.main import create_app

    print(f"Nudgy server on http://{host}:{port}  (Ctrl+C to stop)")
    if env:
        print(f"Settings and keys: {env}")
    # Explicit loop/protocol choices keep the packaged program free of optional extras.
    uvicorn.run(create_app(), host=host, port=port, http="h11", loop="asyncio", ws="none")


if __name__ == "__main__":
    main()
