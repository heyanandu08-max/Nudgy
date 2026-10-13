import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db import init_db
from app.routers import (
    admin,
    ask,
    auth,
    billing,
    client_config,
    health,
    lessons,
    teams,
    walkthroughs,
)


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    settings.check_production_safety()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        yield

    app = FastAPI(title="Nudgy backend", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(client_config.router)
    app.include_router(ask.router)
    app.include_router(lessons.router)
    app.include_router(walkthroughs.router)
    app.include_router(auth.router)
    app.include_router(billing.router)
    app.include_router(teams.router)
    app.include_router(admin.router)
    return app


app = create_app()
