import os

# Tests run against a throwaway in-memory database and fake providers.
os.environ["NUDGY_DATABASE_URL"] = "sqlite://"
os.environ.setdefault("NUDGY_LLM_PROVIDER", "fake")
os.environ.setdefault("NUDGY_STT_PROVIDER", "fake")
os.environ.setdefault("NUDGY_TTS_PROVIDER", "fake")

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:  # runs lifespan (creates tables)
        yield c
