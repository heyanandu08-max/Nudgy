import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.fake import FakeLLM, FakeSTT, FakeTTS
from app.providers.registry import Providers, get_providers

JPEG_URL = "data:image/jpeg;base64,/9j/4AAQ"
RAW = [
    {"kind": "click", "target": {"role": "menuitem", "name": "File"}, "app": "Chrome"},
    {
        "kind": "click",
        "target": {"role": "menuitem", "name": "New incognito window"},
        "app": "Chrome",
    },
    {"kind": "type", "text": "[hidden]", "app": "Chrome"},
    {"kind": "shortcut", "keys": "Ctrl+L", "app": "Chrome", "note": "focus the address bar"},
]


def doc(**kw):
    base = {
        "id": "w-1",
        "title": "Open incognito",
        "app": "Chrome",
        "steps": [
            {
                "instruction": "Click File.",
                "target": {"role": "menuitem", "name": "File"},
                "screenshot": JPEG_URL,
            },
            {"instruction": "Click New incognito window.", "screenshot": JPEG_URL},
        ],
    }
    base.update(kw)
    return base


@pytest.fixture
def providers():
    return Providers(llm=FakeLLM(), stt=FakeSTT(), tts=FakeTTS())


@pytest.fixture
def client(providers):
    app = create_app()
    app.dependency_overrides[get_providers] = lambda: providers
    with TestClient(app) as c:
        yield c


def test_clean_uses_llm_and_clamps_raw_indices(client, providers):
    cleaned = {
        "title": "Open an incognito window",
        "app": "Chrome",
        "summary": "Private browsing.",
        "steps": [
            {
                "instruction": "Open the File menu.",
                "target": {"role": "menuitem", "name": "File"},
                "action_hint": "click",
                "success_check": "Menu open",
                "why": "",
                "raw": [0, 99],
            },
            {
                "instruction": "Choose New incognito window.",
                "target": {"role": "menuitem", "name": "New incognito window"},
                "action_hint": "click",
                "success_check": "Dark window",
                "why": "",
                "raw": [1],
            },
        ],
    }
    providers.llm = FakeLLM(scripted=[json.dumps(cleaned)])
    r = client.post("/v1/walkthroughs/clean", json={"raw": RAW, "app": "Chrome"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Open an incognito window"
    assert body["steps"][0]["raw"] == [0]
    prompt = providers.llm.calls[0]["messages"][0].parts[0]
    assert "1. click menuitem 'New incognito window' in Chrome" in prompt
    assert "[author note: focus the address bar]" in prompt
    assert providers.llm.calls[0]["effort"] == "medium"


def test_clean_falls_back_when_llm_output_is_unusable(client, providers):
    providers.llm = FakeLLM(scripted=["nope", "still nope"])
    body = client.post("/v1/walkthroughs/clean", json={"raw": RAW}).json()
    assert [s["instruction"] for s in body["steps"]] == [
        "Click File.",
        "Click New incognito window.",
        "Type your text.",
        "Press Ctrl+L.",
    ]
    assert body["steps"][3]["why"] == "focus the address bar"
    assert "hidden" not in json.dumps(body)


def test_share_strips_screenshots_by_default_and_fetch_round_trips(client):
    r = client.post("/v1/walkthroughs", json={"walkthrough": doc()})
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    assert r.json()["url"].endswith(f"/w/{slug}")
    got = client.get(f"/v1/walkthroughs/{slug}").json()
    assert got["title"] == "Open incognito"
    assert all(s["screenshot"] is None for s in got["steps"])


def test_share_keeps_screenshots_when_opted_in(client):
    slug = client.post(
        "/v1/walkthroughs", json={"walkthrough": doc(), "include_screenshots": True}
    ).json()["slug"]
    got = client.get(f"/v1/walkthroughs/{slug}").json()
    assert got["steps"][0]["screenshot"] == JPEG_URL


def test_share_rejects_non_jpeg_or_huge_screenshots(client):
    bad = doc(steps=[{"instruction": "x", "screenshot": "data:image/png;base64,AAAA"}])
    assert client.post("/v1/walkthroughs", json={"walkthrough": bad}).status_code == 422
    huge = doc(steps=[{"instruction": "x", "screenshot": JPEG_URL + "A" * 500_000}])
    assert client.post("/v1/walkthroughs", json={"walkthrough": huge}).status_code == 422


def test_unknown_slug_is_404(client):
    r = client.get("/v1/walkthroughs/nope")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"


def test_share_page_escapes_html(client):
    evil = doc(title="<script>alert(1)</script>", steps=[{"instruction": "<b>x</b>"}])
    slug = client.post("/v1/walkthroughs", json={"walkthrough": evil}).json()["slug"]
    page = client.get(f"/w/{slug}")
    assert page.status_code == 200
    assert "<script>" not in page.text and "&lt;script&gt;" in page.text
    assert f"nudgy://w/{slug}" in page.text


def test_transcribe(client):
    r = client.post("/v1/transcribe", files={"audio": ("n.wav", b"RIFF..", "audio/wav")})
    assert r.json() == {"text": "How do I change the font?"}
    r = client.post("/v1/transcribe", files={"audio": ("n.wav", b"", "audio/wav")})
    assert r.json() == {"text": ""}
