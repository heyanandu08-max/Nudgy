import os

# Tests run against a throwaway in-memory database and fake providers.
os.environ["NUDGY_DATABASE_URL"] = "sqlite://"
os.environ.setdefault("NUDGY_LLM_PROVIDER", "fake")
os.environ.setdefault("NUDGY_STT_PROVIDER", "fake")
os.environ.setdefault("NUDGY_TTS_PROVIDER", "fake")

import pytest
from fastapi.testclient import TestClient

from app.db import Base, get_engine, init_db
from app.main import create_app


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts with empty tables in the shared in-memory database."""
    init_db()
    yield
    Base.metadata.drop_all(get_engine())


@pytest.fixture
def client():
    with TestClient(create_app()) as c:  # runs lifespan (creates tables)
        yield c
