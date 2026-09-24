import json
import logging
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import ImagePart, ProviderError
from app.providers.fake import FakeLLM, FakeSTT, FakeTTS
from app.providers.registry import Providers, get_providers
from tests.sse_utils import parse_sse

ELEMENTS = [
    {"id": "e1", "role": "button", "name": "Bold", "rect": {"x": 100, "y": 20, "w": 24, "h": 24}},
    {
        "id": "e2",
        "role": "combobox",
        "name": "Font name",
        "rect": {"x": 10, "y": 20, "w": 80, "h": 24},
    },
]
SCREEN = {"width": 1280, "height": 720}
JPEG = b"\xff\xd8\xff\xe0fakejpeg"


class BrokenTTS(FakeTTS):
    async def synthesize(self, text, *, voice_id, language):
        raise ProviderError("tts_failed", "boom")


class BrokenSTT(FakeSTT):
    async def transcribe(self, audio, *, mime, language):
        raise ProviderError("stt_unreachable", "down", retryable=True)


@pytest.fixture
def providers():
    return Providers(llm=FakeLLM(), stt=FakeSTT(), tts=FakeTTS())


@pytest.fixture
def client(providers):
    app = create_app()
    app.dependency_overrides[get_providers] = lambda: providers
    return TestClient(app)


def ask(client, context: dict, audio=b"RIFFfakewav", screenshot=JPEG):
    files = {}
    if audio is not None:
        files["audio"] = ("q.wav", audio, "audio/wav")
    if screenshot is not None:
        files["screenshot"] = ("s.jpg", screenshot, "image/jpeg")
    r = client.post("/v1/ask", data={"context": json.dumps(context)}, files=files or None)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)


def names(events):
    return [e for e, _ in events]


def test_happy_path_points_at_font_box(client, providers):
    events = ask(client, {"elements": ELEMENTS, "screenshot": SCREEN, "app": {"name": "Notepad"}})
    assert names(events)[0] == "transcript"
    assert events[0][1]["text"] == "How do I change the font?"
    speech = "".join(d["delta"] for e, d in events if e == "speech_text")
    assert "Font name" in speech
    target = next(d for e, d in events if e == "target")
    assert target == {"target": {"element_id": "e2"}, "action_hint": "click"}
    audio = [d for e, d in events if e == "audio"]
    assert audio and [a["seq"] for a in audio] == list(range(len(audio)))
    done = events[-1]
    assert done[0] == "done" and done[1]["speech"] == speech
    assert {"llm_ms", "first_text_ms", "total_ms"} <= done[1]["timings"].keys()
    # The screenshot reached the LLM as an image, with the element list as text.
    msg = providers.llm.calls[0]["messages"][-1]
    assert any(isinstance(p, ImagePart) and p.data == JPEG for p in msg.parts)
    assert "e2 | combobox | Font name | 10,20,80,24" in msg.parts[-1]
    assert '"speech"' in providers.llm.calls[0]["system"]


def test_speech_streams_in_several_deltas(client):
    events = ask(client, {"elements": ELEMENTS, "screenshot": SCREEN})
    assert sum(1 for e, _ in events if e == "speech_text") > 1


def test_typed_question_needs_no_audio(client):
    events = ask(
        client, {"elements": ELEMENTS, "text": "make it bold"}, audio=None, screenshot=None
    )
    assert events[0] == ("transcript", {"text": "make it bold"})
    target = next(d for e, d in events if e == "target")
    assert target["target"] == {"element_id": "e1"}


def test_no_speech_is_an_error(client):
    events = ask(client, {"elements": ELEMENTS}, audio=None)
    assert events == [("error", {"code": "no_speech", "message": "I didn't catch that."})]


def test_invalid_json_is_repaired_with_one_retry(client, providers):
    providers.llm = FakeLLM(
        scripted=[
            "Sure, click the Bold button!",
            '{"speech": "Click Bold.", "target": {"element_id": "e1"}, "action_hint": "click"}',
        ]
    )
    events = ask(client, {"elements": ELEMENTS, "screenshot": SCREEN})
    assert len(providers.llm.calls) == 2
    assert "could not be parsed" in providers.llm.calls[1]["messages"][-1].parts[0]
    assert next(d for e, d in events if e == "target")["target"] == {"element_id": "e1"}
    assert "".join(d["delta"] for e, d in events if e == "speech_text") == "Click Bold."


def test_invalid_json_twice_falls_back_to_speech_only(client, providers):
    providers.llm = FakeLLM(scripted=["Click the Bold button up top.", "still not json"])
    events = ask(client, {"elements": ELEMENTS, "screenshot": SCREEN})
    assert next(d for e, d in events if e == "target")["target"] is None
    assert events[-1][0] == "done"
    assert events[-1][1]["speech"] == "Click the Bold button up top."


def test_streamed_speech_is_kept_when_rest_of_json_breaks(client, providers):
    providers.llm = FakeLLM(
        scripted=['{"speech": "Open the Home tab.", "target": {"element_', "nope"]
    )
    events = ask(client, {"elements": ELEMENTS, "screenshot": SCREEN})
    assert "".join(d["delta"] for e, d in events if e == "speech_text") == "Open the Home tab."
    assert next(d for e, d in events if e == "target")["target"] is None


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ({"element_id": "e99"}, None),
        ({"x": 5000, "y": 10}, None),
        ({"x": 640.4, "y": 360.6}, {"x": 640, "y": 361}),
    ],
)
def test_targets_are_validated(client, providers, target, expected):
    providers.llm = FakeLLM(
        scripted=[json.dumps({"speech": "There.", "target": target, "action_hint": "look"})]
    )
    events = ask(client, {"elements": ELEMENTS, "screenshot": SCREEN})
    assert next(d for e, d in events if e == "target")["target"] == expected


def test_voice_disabled_sends_no_audio(client):
    events = ask(client, {"elements": ELEMENTS, "voice_enabled": False})
    assert "audio" not in names(events) and names(events)[-1] == "done"


def test_tts_failure_is_non_fatal(client, providers):
    providers.tts = BrokenTTS()
    events = ask(client, {"elements": ELEMENTS})
    err = next(d for e, d in events if e == "error")
    assert err["code"] == "tts_failed" and err["fatal"] is False
    assert names(events)[-1] == "done"


def test_stt_failure_reports_error(client, providers):
    providers.stt = BrokenSTT()
    events = ask(client, {"elements": ELEMENTS})
    assert events == [
        (
            "error",
            {
                "code": "stt_unreachable",
                "message": "I couldn't transcribe that. Mind trying again?",
            },
        )
    ]


def test_history_is_trimmed_and_alternates(client, providers):
    history = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"t{i}"} for i in range(30)]
    history.append({"role": "user", "text": "dangling"})
    ask(client, {"elements": ELEMENTS, "history": history})
    msgs = providers.llm.calls[0]["messages"]
    roles = [m.role for m in msgs]
    assert roles[0] == "user" and roles[-1] == "user"
    assert all(a != b for a, b in pairwise(roles))
    assert len(msgs) <= 21


def test_bad_context_is_422(client):
    r = client.post("/v1/ask", data={"context": "{not json"})
    assert r.status_code == 422


def test_screenshot_bytes_never_logged(client, caplog):
    secret = b"\xff\xd8SECRET-PIXELS-" + b"x" * 100
    with caplog.at_level(logging.DEBUG):
        ask(client, {"elements": ELEMENTS}, screenshot=secret)
    assert "SECRET-PIXELS" not in caplog.text
    assert "screenshot_bytes=" in caplog.text  # metadata only
